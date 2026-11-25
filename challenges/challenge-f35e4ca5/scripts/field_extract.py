#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""field_extract.py - 按「目标字段表」驱动抽取（纯标准库、无模型依赖）。

组织方修订版契约（多道阅读题共用）：
    读 /input/target-fields.json 的具体字段，
    每个 field_id 输出一条结果，保留
        value / unit / statistic / experimental condition / comparator /
        exact paragraph_id + quote /
        status ∈ {reported, not_reported, source_conflict, extraction_failed}

铁律（题面原文）：
    * 猜出来的值不算抽取（guessed value is not extraction）
    * 字段缺失不等于 0（an absent field is not zero）
    * 只有字面引文命中也不能证明语义正确（a literal quotation match alone
      does not establish semantic correctness）

本模块的立场：
    * 语义判定**由脚本完成**：字段描述先归一到概念类（dataset / hardware /
      metric / baseline / hyperparameter …），再按概念选词检索、按概念决定
      取值形态（数值型 / 名称型 / 枚举型），最后自检「引文逐字来自原文」
      且「value 是引文的子串」。
    * 找不到证据 → not_reported（绝不填 0、空串或猜测值）。
    * 只有真的找到两处**互斥**原文时才 source_conflict，并在 candidates 里
      列出两处逐字引文；找不到就降级为 reported / not_reported。
    * 文档不可读 / 无文本层 → extraction_failed。
    * 模型复核**退化为可选项**：review_sheet 给出紧凑候选供人工/模型抽检，
      但没有模型介入也能得到完整且自洽的结果集。

  python3 scripts/field_extract.py --input /input --out work/fields.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

STATUS_REPORTED = "reported"
STATUS_NOT_REPORTED = "not_reported"
STATUS_CONFLICT = "source_conflict"
STATUS_FAILED = "extraction_failed"

# --------------------------------------------------------------------- 词典
# 概念词典：字段描述 → 概念类；每个概念带检索词（anchor/support）、取值形态、
# 章节先验。词典同时落在 resources/field_lexicon.json（可被覆盖扩展），
# 本文件内置一份副本，保证打包后不依赖外部资源也能运行。
DEFAULT_LEXICON = {
    "version": "2.0",
    "min_score": 2.0,
    "unit_whitelist": [
        "%", "‰", "×", "倍", "ms", "s", "min", "h", "hr", "hours", "hour",
        "day", "days", "week", "weeks", "GB", "MB", "TB", "KB", "B", "K", "M",
        "G", "words", "word", "tokens", "token", "sentences", "sentence",
        "examples", "example", "samples", "sample", "instances", "documents",
        "layers", "layer", "cells", "cell", "units", "unit", "heads", "head",
        "epochs", "epoch", "iterations", "steps", "parameters", "parameter",
        "frames", "images", "pixels", "points", "fps", "nm", "µm", "mm", "cm",
        "m", "kg", "g", "mg", "W", "kW", "J", "kJ", "eV", "V", "mV", "A",
        "mA", "Hz", "kHz", "MHz", "GHz", "°C", "°F", "Pa", "kPa", "MPa",
        "mol", "L", "mL", "dB", "rpm", "pts",
    ],
    "aliases": {
        "bleu": ["bleu", "bilingual evaluation understudy", "cased bleu"],
        "cider": ["cider", "consensus-based image description evaluation"],
        "rouge": ["rouge", "recall-oriented understudy for gisting evaluation"],
        "ppl": ["perplexity", "ppl"],
        "gpu": ["gpu", "gpus", "graphics processing unit", "nvidia", "tesla",
                "titan", "a100", "v100", "p100", "h100", "rtx"],
        "tpu": ["tpu", "tpus", "tensor processing unit"],
        "na": ["not applicable", "not available", "n/a", "na"],
    },
    "concepts": {
        "dataset": {
            "label": "数据集/语料",
            "type": "name",
            "match": ["dataset", "datasets", "data set", "corpus", "corpora",
                      "benchmark", "data source", "data sources", "training data",
                      "数据集", "语料", "语料库", "训练数据", "测试集", "训练集"],
            "anchor": ["dataset", "data set", "corpus", "corpora",
                       "benchmark", "wmt", "coco", "imagenet", "cifar",
                       "librispeech", "squad", "glue", "superglue"],
            "support": ["subset", "split", "training", "test", "validation",
                        "dev", "data", "sentences", "samples", "examples",
                        "subset", "下载"],
            "sections": ["setup", "method", "intro"],
            "declare": ["we used the", "we train on", "we trained on",
                        "we experiment on", "the dataset consists",
                        "we use the", "dataset is"],
            "strip_head": True,
            "head_nouns": ["dataset", "datasets", "corpus", "corpora", "benchmark"],
        },
        "data_split": {
            "label": "数据划分/比例",
            "type": "name",
            "match": ["split", "partition", "ratio", "划分", "比例", "切分"],
            "anchor": ["split", "partition", "ratio", "train/valid", "train/dev"],
            "support": ["training", "validation", "test", "dev", "percent", "%"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": ["split", "splits", "partition", "ratio"],
        },
        "data_size": {
            "label": "数据规模（样本数）",
            "type": "number",
            "match": ["number of samples", "sample size", "data size",
                      "dataset size", "how many samples", "样本数", "数据量"],
            "anchor": ["samples", "instances", "examples", "sentences",
                       "images", "documents", "examples"],
            "support": ["training", "test", "dataset", "corpus", "total", "we used"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "model_architecture": {
            "label": "模型架构",
            "type": "name",
            "match": ["architecture", "model structure", "network structure",
                      "model", "network", "framework", "backbone", "encoder",
                      "decoder", "架构", "模型", "网络", "结构"],
            "anchor": ["lstm", "rnn", "transformer", "cnn", "bert", "gpt",
                       "resnet", "vgg", "unet", "seq2seq", "encoder-decoder",
                       "encoder decoder", "attention", "model", "network",
                       "architecture", "lstm", "mlp", "svm", "lda", "knn"],
            "support": ["layer", "layers", "unit", "units", "cell", "cells",
                        "embedding", "hidden", "state", "parameter", "parameters",
                        "layer", "attention", "softmax", "激活"],
            "sections": ["method", "setup", "preamble"],
            "declare": ["our method", "our model", "we used", "we use",
                        "the model", "we trained", "architecture"],
            "strip_head": False,
            "head_nouns": ["model", "models", "network", "networks",
                           "architecture", "baseline", "system", "framework"],
        },
        "model_size": {
            "label": "模型规模/参数量",
            "type": "number",
            "match": ["model size", "parameter count", "number of parameters",
                      "parameters", "参数量", "模型规模"],
            "anchor": ["parameters", "parameter", "params"],
            "support": ["million", "billion", "weights", "size", "total", "uses"],
            "sections": ["setup", "method", "results"],
            "strip_head": False,
            "head_nouns": [],
        },
        "hardware": {
            "label": "硬件/算力",
            "type": "name",
            "match": ["hardware", "gpu", "gpus", "tpu", "cpu", "accelerator",
                      "device", "compute node", "server", "显卡", "硬件", "算力",
                      "机器", "服务器"],
            "anchor": ["gpu", "tpu", "cpu", "accelerator",
                       "nvidia", "tesla", "titan", "a100", "v100", "p100",
                       "h100", "cuda", "gpu machine", "gpu cluster"],
            "support": ["machine", "node", "nodes", "server", "servers", "card",
                        "cards", "processor", "processors", "parallel", "memory",
                        "ram", "显存", "并行"],
            "sections": ["setup", "method"],
            "declare": ["we parallelized", "we used", "trained on", "using an",
                        "using a", "we train", "on a"],
            "strip_head": False,
            "head_nouns": ["machine", "machines", "node", "nodes", "server",
                           "servers", "device", "devices", "card", "cards",
                           "cluster", "gpu", "gpus", "tpu", "tpus", "processor",
                           "processors", "system"],
        },
        "compute_time": {
            "label": "训练/推理耗时",
            "type": "number",
            "match": ["training time", "runtime", "run time", "wall-clock",
                      "wall clock", "time per", "training hours", "computation time",
                      "耗时", "训练时间", "运行时间"],
            "anchor": ["hours", "hour", "days", "day", "minutes", "seconds",
                       "h", "gpu-hours", "wall-clock", "wall clock"],
            "support": ["trained", "training", "took", "required", "about",
                        "approximately", "total", "per"],
            "sections": ["setup", "results"],
            "strip_head": False,
            "head_nouns": [],
        },
        "implementation": {
            "label": "实现/框架/语言",
            "type": "name",
            "match": ["implementation", "framework", "programming language",
                      "software", "library", "实现", "框架", "编程语言"],
            "anchor": ["pytorch", "tensorflow", "keras", "jax", "numpy", "scipy",
                       "cuda", "c++", "python", "java", "matlab", "mxnet",
                       "theano", "torch"],
            "support": ["implemented", "implementation", "code", "library",
                        "version", "written"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": ["implementation", "framework", "library"],
        },
        "metric": {
            "label": "评测指标",
            "type": "name",
            "alias_keys": ["bleu", "cider", "rouge", "ppl"],
            "match": ["metric", "metrics", "evaluation metric", "evaluation measure",
                      "scoring function", "评测指标", "评价指标", "指标"],
            "anchor": ["bleu", "cider", "rouge", "perplexity", "ppl", "f1",
                       "accuracy", "precision", "recall", "wer", "cer", "meteor",
                       "chrf", "map", "auc", "roc", "rmse", "mae", "mse", "psnr",
                       "ssim", "iou", "miou", "fid", "lpips", "r2", "nll",
                       "cross-entropy", "cross entropy", "loss", "score"],
            "support": ["evaluate", "evaluating", "evaluation", "measured",
                        "measure", "metric", "score", "scoring", "computed",
                        "computed", "accuracy"],
            "sections": ["results", "setup", "method"],
            "declare": ["to evaluate", "to measure", "evaluation metric",
                        "we used", "we compute", "measured by", "we report"],
            "strip_head": False,
            "acronym_only": True,
            "head_nouns": ["score", "scores", "metric", "metrics"],
        },
        "metric_value": {
            "label": "指标数值",
            "type": "number",
            "match": ["accuracy value", "metric value", "score value",
                      "指标数值", "准确率数值"],
            "anchor": ["accuracy", "f1", "precision", "recall", "bleu", "rmse",
                       "auc", "psnr", "ssim"],
            "support": ["score", "value", "reached", "achieves", "obtained",
                        "of", "%"],
            "sections": ["results"],
            "strip_head": False,
            "head_nouns": [],
        },
        "result_value": {
            "label": "主要结果数值",
            "type": "number",
            "match": ["main result", "headline result", "best result",
                      "key result", "performance result", "主要结果", "关键结果"],
            "anchor": ["score", "accuracy", "bleu", "f1", "improvement",
                       "outperform", "achieves", "achieve", "obtained",
                       "reaches", "results"],
            "support": ["of", "on", "with", "test", "set", "%,", "points"],
            "sections": ["results", "preamble"],
            "strip_head": False,
            "head_nouns": [],
        },
        "baseline": {
            "label": "比较基线",
            "type": "name",
            "match": ["baseline", "baselines", "base system", "reference system",
                      "compared against", "comparison system", "基线", "对照系统",
                      "对比系统"],
            "anchor": ["baseline", "baselines", "baseline system", "reference system",
                       "state-of-the-art", "state of the art", "phrase-based",
                       "smt", "nmt", "rule-based", "statistical", "conventional"],
            "support": ["compared", "comparison", "versus", "vs", "against",
                        "outperform", "better than", "relative to", "than",
                        "we compare", "compared with"],
            "sections": ["results", "intro", "method"],
            "strip_head": False,
            "head_nouns": ["baseline", "baselines", "system", "systems", "model",
                           "approach", "method"],
        },
        "comparator": {
            "label": "对比对象",
            "type": "name",
            "match": ["comparator", "comparison target", "compared with whom",
                      "对比对象", "对照"],
            "anchor": ["compared to", "compared with", "versus", "vs",
                       "relative to", "against", "than"],
            "support": ["baseline", "compared", "comparison", "outperform",
                        "higher", "lower", "better", "worse"],
            "sections": ["results"],
            "strip_head": False,
            "head_nouns": ["baseline", "system", "model"],
        },
        "statistic": {
            "label": "统计量/误差",
            "type": "name",
            "match": ["statistic", "statistics", "standard deviation",
                      "confidence interval", "p-value", "significance",
                      "error bar", "统计量", "标准差", "置信区间", "显著性"],
            "anchor": ["standard deviation", "std", "stderr", "variance",
                       "confidence interval", "ci", "p-value", "p value", "p<",
                       "p <", "significant", "significance", "median", "mean",
                       "quartile", "iqr"],
            "support": ["error", "errors", "bars", "interval", "significant",
                        "over", "average"],
            "sections": ["results"],
            "strip_head": False,
            "head_nouns": ["interval", "deviation"],
        },
        "experimental_condition": {
            "label": "实验条件",
            "type": "name",
            "match": ["experimental condition", "experiment condition",
                      "under which", "实验条件", "测试条件"],
            "anchor": ["under", "with", "on", "setting", "condition", "setup",
                       "configuration"],
            "support": ["dataset", "test", "set", "split", "seed", "budget",
                        "batch", "model"],
            "sections": ["setup", "results"],
            "strip_head": False,
            "head_nouns": ["setting", "settings", "condition", "conditions"],
        },
        "beam_size": {
            "label": "beam 宽度",
            "type": "number",
            "match": ["beam size", "beam width", "beam search size",
                      "number of beams", "beam", "束宽", "beam 宽度"],
            "anchor": ["beam size", "beam width", "beam search size", "beam of size",
                       "beam"],
            "support": ["decoder", "decoding", "search", "hypothesis",
                        "hypotheses", "greedy"],
            "sections": ["setup", "results"],
            "strip_head": False,
            "head_nouns": [],
        },
        "learning_rate": {
            "label": "学习率",
            "type": "number",
            "match": ["learning rate", "学习率"],
            "anchor": ["learning rate", "lr"],
            "support": ["sgd", "adam", "optimizer", "momentum", "decay",
                        "schedule", "halving"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "batch_size": {
            "label": "批大小",
            "type": "number",
            "match": ["batch size", "batchsize", "mini-batch size", "minibatch size",
                      "批大小", "批次大小"],
            "anchor": ["batch size", "batchsize", "minibatch size", "mini-batch size",
                       "batches of", "batch of"],
            "support": ["batch", "batches", "gradient", "minibatch", "mini-batch"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "vocab_size": {
            "label": "词表大小",
            "type": "number",
            "match": ["vocabulary size", "vocab size", "vocabulary",
                      "word list size", "词表大小", "词表"],
            "anchor": ["vocabulary size", "vocab size", "vocabulary", "vocab",
                       "word list", "lexicon"],
            "support": ["words", "word", "tokens", "token", "frequency",
                        "frequent", "source", "target", "input", "output"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "num_layers": {
            "label": "层数/隐藏单元数",
            "type": "number",
            "match": ["number of layers", "layer count", "depth of the network",
                      "hidden size", "hidden units", "hidden dimension",
                      "层数", "隐藏层"],
            "anchor": ["layers", "layer", "hidden units", "hidden size", "hidden",
                       "units at each layer", "cells at each layer"],
            "support": ["network", "model", "lstm", "transformer", "deep", "each"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "epochs": {
            "label": "训练轮数",
            "type": "number",
            "match": ["number of epochs", "epochs", "epoch count", "training epochs",
                      "训练轮数", "迭代轮数"],
            "anchor": ["epochs", "epoch", "iterations", "steps", "passes"],
            "support": ["trained", "training", "for a total of", "we trained"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "dropout": {
            "label": "dropout",
            "type": "number",
            "match": ["dropout", "drop-out", "dropout rate", "dropout probability",
                      "正则化率"],
            "anchor": ["dropout", "drop-out", "dropout rate", "dropout probability"],
            "support": ["regularization", "overfitting", "rate", "probability"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "optimizer": {
            "label": "优化器",
            "type": "name",
            "match": ["optimizer", "optimiser", "optimization algorithm",
                      "优化器", "优化算法"],
            "anchor": ["sgd", "adam", "adagrad", "rmsprop", "adom", "momentum",
                       "gradient descent", "adamw", "lbfgs"],
            "support": ["optimizer", "optimization", "learning rate", "momentum"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "regularization": {
            "label": "正则化",
            "type": "name",
            "match": ["regularization", "regularisation", "weight decay",
                      "l2 norm", "正则化"],
            "anchor": ["regularization", "weight decay", "l2", "l1", "norm",
                       "constraint", "clipping", "early stopping"],
            "support": ["overfitting", "generalization", "training"],
            "sections": ["setup", "method"],
            "strip_head": False,
            "head_nouns": [],
        },
        "ablation": {
            "label": "消融实验",
            "type": "name",
            "match": ["ablation", "ablation study", "ablation study results",
                      "component analysis", "消融"],
            "anchor": ["ablation", "ablation study", "without the", "removing the",
                       "w/o", "variant"],
            "support": ["component", "components", "compare", "effect", "impact",
                        "contribution"],
            "sections": ["results"],
            "strip_head": False,
            "head_nouns": [],
        },
        "limitation": {
            "label": "局限",
            "type": "text",
            "match": ["limitation", "limitations", "threats to validity",
                      "drawback", "shortcoming", "局限", "不足", "限制"],
            "anchor": ["limitation", "limitations", "cannot", "can not",
                       "does not", "do not", "unable to", "future work",
                       "threats to validity", "drawback", "shortcoming"],
            "support": ["however", "but", "although", "restrict", "fails",
                        "unable", "problem", "assumption", "assumption-free"],
            "sections": ["limitation", "conclusion", "discussion"],
            "strip_head": False,
            "head_nouns": [],
        },
        "speed": {
            "label": "吞吐/速度",
            "type": "number",
            "match": ["throughput", "speed", "words per second", "latency",
                      "samples per second", "吞吐", "速度"],
            "anchor": ["words per second", "samples per second", "throughput",
                       "speed", "per second", "latency"],
            "support": ["processes", "achieves", "speedup", "parallel",
                        "implementation", "batch"],
            "sections": ["setup", "results"],
            "strip_head": False,
            "head_nouns": [],
        },
        "general": {
            "label": "通用（无明确概念）",
            "type": "name",
            "match": [],
            "anchor": [],
            "support": [],
            "sections": [],
            "strip_head": False,
            "head_nouns": [],
        },
    },
}

LEXICON_FILES = (
    os.path.join(HERE, "..", "resources", "field_lexicon.json"),
    os.path.join(HERE, "..", "..", "skills-core", "resources", "field_lexicon.json"),
)


def _deep_merge(base, extra):
    """把 extra 合并进 base 的副本（dict 递归，list 覆盖）。"""
    out = copy.deepcopy(base)
    for key, val in (extra or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def load_lexicon(path=None):
    """加载概念词典：内置副本 + resources/field_lexicon.json 的覆盖扩展。"""
    lex = copy.deepcopy(DEFAULT_LEXICON)
    candidates = [path] if path else list(LEXICON_FILES)
    for cand in candidates:
        if not cand or not os.path.isfile(cand):
            continue
        try:
            with open(cand, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        # 只有带 concepts 键的文件才当词典用（打包后的 field_lexicon.json 是
        # 题面元数据，不能当概念词典覆盖）。
        if not isinstance(data.get("concepts"), dict):
            continue
        lex = _deep_merge(lex, data)
        break
    return lex


# ------------------------------------------------------------------- 基础件
STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "by",
    "is", "are", "was", "were", "be", "been", "that", "this", "these", "those",
    "as", "at", "from", "its", "it", "which", "what", "any", "all", "each",
    "reported", "report", "value", "values", "field", "fields", "please",
    "extract", "extraction", "state", "give", "provide", "list", "identify",
    "结果", "字段", "提取", "抽取", "请", "给出", "列出", "说明", "包含",
    "对应", "相关", "以及", "其中", "是否", "该", "一个", "所有", "used", "use",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}|[\u4e00-\u9fff]{2,}|\d+(?:\.\d+)?%?")
SENT_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n{2,}")

DESC_KEYS = ("description", "desc", "question", "scope", "prompt", "label",
              "name", "definition", "instruction", "hint", "meaning", "field",
              "content", "requirement")

ID_KEYS = ("field_id", "fieldId", "id", "key", "name", "field", "label",
           "column", "slug", "field_name")

# 名称型取值时，向左扩展允许吸收的修饰词 / 限定词
MODIFIER_WORDS = {
    "the", "a", "an", "our", "its", "their", "this", "these", "those", "his",
    "her", "deep", "large", "small", "big", "cased", "uncased", "fixed",
    "naive", "standard", "conventional", "classical", "phrase-based",
    "rule-based", "statistical", "neural", "recurrent", "convolutional",
    "bidirectional", "multi-layer", "multilayer", "multi", "pre-trained",
    "pretrained", "fine-tuned", "fine", "source", "target", "input", "output",
    "best", "baseline", "test", "training", "validation", "dev", "single",
    "double", "full", "new", "original", "base", "end-to-end", "low-rank",
    "residual", "attention", "based", "final", "whole", "entire", "separate",
    "remaining", "different", "same", "total", "main", "other", "next", "no",
    "first", "second", "third", "last", "two", "three", "four", "five", "六",
}

# 名称型取值时，向右扩展允许吸收的连接词
CONNECTORS = {"to", "and", "-", "’s", "'s", "de", "la", "du", "von", "der", "of"}

# 名称型取值时，首部要剥掉的限定词
DETERMINERS = {"the", "a", "an", "our", "its", "their", "this", "these",
               "those", "his", "her", "such"}

CONTRAST_RE = re.compile(
    r"\b(?:however|but|although|whereas|in\s+contrast|unlike|instead\s+of|"
    r"on\s+the\s+other\s+hand|nevertheless|yet|contradict\w*|inconsistent)\b|"
    r"但是|然而|不过|相反|而", re.I)

COMPARATOR_RE = re.compile(
    r"\b(?:vs\.?|versus|compared\s+(?:to|with)|relative\s+to|baseline|"
    r"outperform\w*|against|higher\s+than|lower\s+than|better\s+than|"
    r"worse\s+than|improv\w*\s+(?:over|on))\b|相比|对照|基线|优于", re.I)

NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9'’.])"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<scale>\s*[kKmMbBGT])?"
    r"(?![A-Za-z0-9])")

YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def tokenize(text):
    """把字段描述切成检索词：英文词 + 中文短语 + 数字。"""
    if not text:
        return []
    out = []
    for tok in TOKEN_RE.findall(text):
        low = tok.lower()
        if low in STOPWORDS:
            continue
        if len(tok) == 1:
            continue
        out.append(tok)
    seen, uniq = set(), []
    for t in out:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq


def load_target_fields(input_dir):
    """读取 /input/target-fields.json（容错：也接受 fields.json / target_fields.json）。"""
    for name in ("target-fields.json", "target_fields.json", "fields.json",
                 "target-field-list.json", "target_fields_list.json"):
        path = os.path.join(input_dir, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh), path
            except Exception:
                continue
    try:
        for name in sorted(os.listdir(input_dir)):
            if name.lower().endswith(".json") and "field" in name.lower():
                path = os.path.join(input_dir, name)
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh), path
    except OSError:
        pass
    return None, None


def normalize_fields(spec):
    """把不同形状的字段表归一成 [{field_id, description, _text}]。

    兼容形状：
        {"fields": [...]} / {"target_fields": [...]} / 顶层 list /
        {"field_id": {...}} 映射 / {"field_id": "说明"} 映射
    字段描述可能落在 field_id/description/name/label/question/scope/prompt
    任一键上：全部并集进 _text 做检索词，description 取第一个非空说明。
    """
    items = []
    if isinstance(spec, dict):
        picked = None
        for key in ("fields", "target_fields", "targetFields", "items", "required",
                    "columns", "field_list", "schema", "spec"):
            val = spec.get(key)
            if isinstance(val, list) and val:
                picked = val
                break
            if isinstance(val, dict) and val:
                picked = [dict(v, field_id=v.get("field_id", k))
                          for k, v in val.items() if isinstance(v, dict)]
                break
        if picked is not None:
            items = picked
        else:
            for k, v in spec.items():
                if isinstance(v, dict):
                    d = dict(v)
                    d.setdefault("field_id", k)
                    items.append(d)
                elif isinstance(v, str):
                    items.append({"field_id": k, "description": v})
    elif isinstance(spec, list):
        items = spec

    out = []
    for idx, it in enumerate(items, 1):
        if isinstance(it, str):
            out.append({"field_id": it, "description": it, "_text": it})
            continue
        if not isinstance(it, dict):
            continue
        fid, fid_key = None, None
        for k in ID_KEYS:
            v = it.get(k)
            if isinstance(v, (str, int)) and str(v).strip():
                fid, fid_key = str(v).strip(), k
                break
        if not fid:
            fid = "field_%d" % idx
        texts = []
        for k in DESC_KEYS:
            if k == fid_key:
                continue
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                texts.append(v.strip())
        if not texts:
            texts.append(fid)
        desc = texts[0]
        rec = {"field_id": fid, "description": desc,
               "_text": " ".join([fid] + texts)}
        extra = {k: v for k, v in it.items()
                 if k not in ID_KEYS and k not in DESC_KEYS}
        if extra:
            rec["spec"] = extra
        out.append(rec)
    return out


# ------------------------------------------------------------------- 文档层
def _section_kind(title, role, unit_text=None):
    """把章节标题归成粗粒度类别（比 doc_extract.role_of 更细）。"""
    t = re.sub(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]{1,6}\.?)\s*", "", (title or "")).strip().lower()
    # 参考文献条目：标题里带年份且很短
    if re.search(r"\b(19|20)\d{2}\b", t) and len(t) < 70:
        return "references"
    if any(k in t for k in ("setup", "dataset", "training detail", "implementation",
                            "parallel", "decoding", "rescor", "revers", "data and",
                            "material", "experimental setting", "configuration")):
        return "setup"
    if any(k in t for k in ("result", "evaluation", "experiment", "performance",
                            "analysis", "finding", "ablation", "benchmark")):
        return "results"
    if any(k in t for k in ("model", "method", "approach", "architect", "algorithm",
                            "network", "formulation", "objective", "training")):
        return "method"
    if "introduction" in t:
        return "intro"
    if "related" in t:
        return "related"
    if "conclusion" in t:
        return "conclusion"
    if "limitation" in t:
        return "limitation"
    if "acknowledg" in t:
        return "ack"
    if "reference" in t:
        return "references"
    if "appendix" in t or "supplement" in t:
        return "appendix"
    if "discussion" in t:
        return "discussion"
    if role == "preamble":
        return "preamble"
    return role or "other"


def _sentences(doc):
    """展开成 [{text, page, section, sentence, anchor, kind}]。

    切句必须与 doc_extract.split_sentences 完全一致，否则句子序号与
    doc["numbers"] 里的锚点会错位，数值就挂不到正确的句子上。
    """
    try:
        import doc_extract
        splitter = doc_extract.split_sentences
        page_at = doc_extract.page_at_offset
    except Exception:
        splitter = lambda t: [p.strip() for p in SENT_SPLIT_RE.split(t or "") if p.strip()]
        page_at = None
    rows = []
    for u in doc.get("units", []):
        text = u.get("text", "")
        spans = u.get("spans") or []
        kind = _section_kind(u.get("title"), u.get("role"), text)
        # 参考文献区域：单元内的独立 "References" 标题之后
        ref_offset = None
        for m in re.finditer(r"(?im)^[ \t]*references?[ \t]*$", text or ""):
            ref_offset = m.end()
        offset = 0
        for k, sent in enumerate(splitter(text), 1):
            s = (sent or "").strip()
            if len(s) < 12:
                continue
            page = u.get("page_start")
            idx = offset
            if page_at and spans:
                idx = text.find(s, offset)
                if idx < 0:
                    idx = offset
                page = page_at(spans, idx) or page
                offset = idx + len(s)
            skind = kind
            if ref_offset is not None and idx >= ref_offset:
                skind = "references"
            elif _looks_like_reference(s):
                skind = "references"
            rows.append({"text": s, "page": page, "section": u["id"],
                         "sentence": k, "kind": skind,
                         "anchor": "p.%d/%s/sent.%d" % (page, u["id"], k)})
    return rows


GENERIC_ANCHORS = {
    "model", "models", "network", "networks", "architecture", "system",
    "systems", "method", "methods", "approach", "approaches", "score",
    "scores", "result", "results", "value", "values", "loss", "function",
    "functions", "state", "states", "unit", "units", "code", "data",
}

REFERENCE_SENT_RE = re.compile(
    r"\b(?:In\s+Proceedings|Proceedings\s+of|arXiv\s+preprint|"
    r"arXiv:\d|IEEE\s+Transactions|Advances\s+in\s+Neural|Conference\s+on|"
    r"Journal\s+of\s+Machine|Transactions\s+on\s+Neural|ICLR|NeurIPS|NIPS|"
    r"EMNLP|CVPR|ICCV|ECCV|AAAI|JMLR|Speech\s+Association|Transactions\s+of\s+the\s+Association)\b"
    r"|\bpp?\.\s*\d+|\bvol\.\s*\d+",
    re.I)


def _looks_like_reference(sentence):
    """句子是否是参考文献条目（作者 + 会议/期刊 + 年份）。

    注意：结果表格里也会出现 "[2]  28.45" 这种以方括号编号开头的行，
    不能因为开头是 "[n]" 就当参考文献——只有编号后紧跟作者署名
    （"[5] K. Cho, ..." / "[9] Nadir Durrani, ..."）才是文献条目。
    """
    txt = (sentence or "").strip()
    if not txt:
        return False
    m = re.match(r"^\[(\d{1,3})\]\s*(.*)$", txt, re.S)
    if m:
        rest = m.group(2).strip()
        if not rest:
            return False
        # 编号后是分数/数值 → 表格行；是作者署名 → 参考文献条目
        if re.match(r"^\d", rest):
            return False
        if re.match(r"^[A-Z][a-zA-Z'\-]*\s+[A-Z]", rest) or re.match(r"^[A-Z]\.\s", rest):
            return True
        return False
    if len(txt) > 320:
        return False
    if not REFERENCE_SENT_RE.search(txt):
        return False
    return bool(re.search(r"\b(19|20)\d{2}\b", txt))


def _term_weight(term, is_acronym=False):
    """检索词权重：多词短语/缩写最具体，泛化名词降权。"""
    t = (term or "").lower()
    if not t:
        return 0.0
    if t.isdigit():
        return 0.5
    base = 2.0
    if " " in t or "-" in t:
        base = 3.0
    elif t.isupper() and len(t) >= 2:
        base = 3.0
    elif len(t) >= 8:
        base = 2.0
    elif len(t) >= 5:
        base = 1.5
    else:
        base = 1.0
    if is_acronym:
        base = max(base, 3.0)
    if t in GENERIC_ANCHORS:
        base *= 0.45
    return base


def _term_pattern(term):
    """词边界匹配（允许复数 s/es 后缀）。"""
    t = (term or "").lower()
    return re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?:s|es)?(?![a-z0-9])")


def _contains(text_low, term):
    """词边界包含判断（term 小写）。"""
    if not term:
        return False
    return _term_pattern(term).search(text_low) is not None


def _concept_terms(concept, lex):
    """概念的三类词：anchor（强）/ support（弱）/ 别名展开。"""
    anchor = list(concept.get("anchor", []))
    support = list(concept.get("support", []))
    for key in concept.get("alias_keys", []):
        for extra in lex.get("aliases", {}).get(key, []):
            if extra not in anchor:
                anchor.append(extra)
    seen, uniq_anchor, uniq_support = set(), [], []
    for t in anchor:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            uniq_anchor.append(t)
    for t in support:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            uniq_support.append(t)
    return uniq_anchor, uniq_support


def classify_field(field, lex):
    """把字段归到一个概念类。

    返回 (concept_name, confidence, matched_terms)。
    依据：field_id + 各说明键的并集文本里命中了该概念的 match 词。
    """
    text = (field.get("_text") or field.get("description") or "").lower()
    fid = (field.get("field_id") or "").lower()
    best, best_score, best_hits = "general", 0.0, []
    for name, concept in lex.get("concepts", {}).items():
        if name == "general":
            continue
        score, hits = 0.0, []
        for term in concept.get("match", []):
            t = term.lower()
            if _contains(text, t):
                w = 1.0 + min(len(t), 14) / 14.0
                if _contains(fid, t):
                    w *= 1.4
                score += w
                hits.append(term)
        if score > best_score + 1e-9:
            best, best_score, best_hits = name, score, hits
    if best_score < 1.2:
        return "general", 0.0, []
    return best, round(best_score, 2), best_hits


def _anchor_hits(sent_text, anchor_terms):
    """返回 [(term, count, first_start, first_end, is_acronym)]：概念强词命中。

    is_acronym 表示该处原文是大写缩写（LSTM / BLEU / GPU …），缩写比普通
    单词更能确定「本文用的就是它」，权重更高。
    """
    low = (sent_text or "").lower()
    raw = []
    for term in anchor_terms:
        found = list(_term_pattern(term).finditer(low))
        if not found:
            continue
        first = found[0]
        span = (sent_text or "")[first.start():first.end()].strip("()[]{}.,;:")
        if span.lower().endswith("s") and len(span) > 2:
            span = span[:-1]
        is_acronym = span.isupper() and len(span) >= 2
        raw.append((term, len(found), first.start(), first.end(), is_acronym))
    raw.sort(key=lambda x: (-_term_weight(x[0], x[4]), x[2]))
    # 同一段文字被多个词命中时只保留权重最高的那个（避免 gpu/gpus 重复计分）
    out, taken = [], []
    for item in raw:
        s, e = item[2], item[3]
        if any(not (e <= ts or s >= te) for ts, te in taken):
            continue
        taken.append((s, e))
        out.append(item)
    return out


def score_sentence(sent, anchor_terms, support_terms, field_terms, concept, lex):
    """句级打分：概念词命中 + 术语加权 + 邻近度 + 章节先验。

    返回 (score, hits, anchor_hit_count)。
    """
    low = sent["text"].lower()
    hits, score, n_anchor = [], 0.0, 0
    for term, count, _s, _e, is_acr in _anchor_hits(sent["text"], anchor_terms):
        w = _term_weight(term, is_acr)
        score += w * (1.0 + 0.15 * (count - 1))
        n_anchor += 1
        hits.append(term)
    sup = 0.0
    for term in support_terms:
        if _contains(low, term):
            sup += 0.3 * _term_weight(term)
            hits.append(term)
    score += min(sup, 0.9)
    for term in field_terms[:6]:
        if _contains(low, term):
            score += 0.15
            hits.append(term)
    kind = sent.get("kind", "other")
    if kind in concept.get("sections", []):
        score += 0.8
    if kind in ("references", "related", "appendix"):
        score -= 1.2
    return score, hits, n_anchor


def _numbers_in_sentence(text, unit_whitelist):
    """句内数值（带位置与单位），只保留白名单单位。"""
    units = set(unit_whitelist)
    try:
        import doc_extract
        units |= set(doc_extract.KNOWN_UNITS)
    except Exception:
        pass
    out = []
    for m in NUMBER_RE.finditer(text or ""):
        num = m.group("num")
        if not num or not re.search(r"\d", num):
            continue
        # 参考文献编号 [29] / (2014) 之类不是测量值
        before = text[max(0, m.start() - 1):m.start()]
        after = text[m.end():m.end() + 1]
        if before in ("[", "(") or after in ("]", ")"):
            continue
        scale = (m.group("scale") or "").strip()
        unit = ""
        tail = text[m.end():m.end() + 16]
        um = re.match(r"\s*([A-Za-zµμΩ%][A-Za-zµμΩ/%·\-]{0,11})", tail)
        if um:
            cand = um.group(1)
            if cand in units:
                unit = cand
        value = num + (scale or "")
        out.append({"raw": value, "num": num, "scale": scale, "unit": unit,
                    "start": m.start(), "end": m.end(),
                    "is_year": bool(YEAR_RE.match(num))})
    return out


def _has_doc_extract():
    try:
        import doc_extract  # noqa: F401
        return True
    except Exception:
        return False


# --------------------------------------------------------------- 取值：数值型
def _pick_number(sent_text, anchor_terms, nums, concept):
    """在句内选出最贴合概念的数值。

    规则：优先「紧跟在概念词后面」的数（beam size of 5 / vocabulary of
    80,000）；取最近的一次概念词命中作为参照；同等距离取更靠右的那个
    （input vocabulary of 160,000 and an output vocabulary of 80,000 → 80,000）。
    """
    if not nums:
        return None
    low = (sent_text or "").lower()
    positions = []
    for term in anchor_terms:
        for m in _term_pattern(term).finditer(low):
            positions.append(m.end())
    best, best_key = None, None
    for n in nums:
        after = [p for p in positions if p <= n["start"]]
        before = [p for p in positions if p > n["end"]]
        if after:
            dist = n["start"] - max(after)
            direction = 0.0
        elif before:
            dist = min(before) - n["end"]
            direction = 1.5
        else:
            dist, direction = 999.0, 3.0
        fit = 0.0
        if n["unit"]:
            fit += 0.6
        if n["is_year"] and concept != "general":
            fit -= 2.0
        key = (round(direction, 2), dist, -n["start"], -fit)
        if best_key is None or key < best_key:
            best, best_key = n, key
    return best


# --------------------------------------------------------------- 取值：名称型
def _tokens_with_offsets(text):
    return [(m.group(0), m.start(), m.end())
            for m in re.finditer(r"\S+", text or "")]


def _tok_clean(tok):
    return tok.strip("()[]{}<>,.;:!?\"'“”‘’…—–")


def _is_name_like(tok):
    """是否像专有名词 / 缩写 / 带数字的型号。"""
    t = _tok_clean(tok)
    if not t:
        return False
    if re.search(r"\d", t):
        return True
    if t.isupper() and len(t) >= 2:
        return True
    if t[:1].isupper():
        return True
    return False


def _strip_edges(phrase):
    """去掉首尾标点，但保留成对括号（"(LSTM)" 不能被截成 "(LSTM"）。

    只裁剪**没有配对**的括号，成对的 "(LSTM)" / "(a.k.a. X)" 原样保留，
    以保证取值是原文连续子串。
    """
    s = phrase.strip(" \t\n,;:.\"'“”")
    while s:
        head, tail = s[0], s[-1]
        if head in "([{":
            if s.count(head) <= s.count({")": ")", "(": "(", "[": "[", "{": "{"}[head]):
                break
            s = s[1:].lstrip(" \t\n,;:.\"'“”")
            continue
        if tail in ")]}":
            if s.count(tail) <= s.count({")": ")", "(": "(", "[": "[", "{": "{"}[tail]):
                break
            s = s[:-1].rstrip(" \t\n,;:.\"'“”")
            continue
        break
    return s


def _extract_name_value(sent_text, anchor_term, anchor_end, concept):
    """名称型取值：概念词附近的名词短语（原文连续子串）。"""
    toks = _tokens_with_offsets(sent_text)
    if not toks:
        return None
    core = None
    for i, (tok, s, e) in enumerate(toks):
        if s < anchor_end <= e:
            core = i
            break
    if core is None:
        core = 0
        for i, (tok, s, e) in enumerate(toks):
            if e <= anchor_end:
                core = i
    # 找到包含 anchor 的 token（anchor 可能落在 token 内部，如 "8-GPU"）
    while core > 0 and toks[core][1] >= anchor_end:
        core -= 1

    # 向左扩展：修饰词 / 限定词 / 专有名词 / 连接词（不跨换行）
    left = core
    while left > 0 and (core - left) < 6:
        prev = _tok_clean(toks[left - 1][0])
        if not prev or "\n" in toks[left - 1][0]:
            break
        if (prev.lower() in MODIFIER_WORDS or prev.lower() in CONNECTORS
                or _is_name_like(toks[left - 1][0])):
            left -= 1
            continue
        break
    # 向右扩展：专有名词 / 连接词 / 概念允许的中心词
    head_nouns = {h.lower() for h in concept.get("head_nouns", [])}
    right = core
    while right < len(toks) - 1 and (right - core) < 6:
        nxt = _tok_clean(toks[right + 1][0])
        if not nxt:
            break
        if _is_name_like(toks[right + 1][0]) or nxt.lower() in CONNECTORS:
            right += 1
            continue
        if nxt.lower() in head_nouns:
            right += 1
            continue
        break
    start = toks[left][1]
    end = toks[right][2]
    phrase = sent_text[start:end]
    # 去掉尾部连接词
    while right > core and _tok_clean(toks[right][0]).lower() in CONNECTORS:
        right -= 1
        end = toks[right][2]
        phrase = sent_text[start:end]
    # 去掉首尾标点（括号要成对保留："(LSTM)" 不能被截成 "(LSTM"）
    phrase = _strip_edges(phrase)
    # 去掉首部限定词（the / a / an / our …）
    while True:
        parts = phrase.split(" ", 1)
        if len(parts) == 2 and _tok_clean(parts[0]).lower() in DETERMINERS:
            phrase = parts[1].lstrip()
            continue
        break
    if concept.get("strip_head"):
        for h in sorted(head_nouns, key=len, reverse=True):
            if phrase.lower().endswith(" " + h.lower()):
                phrase = phrase[:-(len(h) + 1)].strip()
                break
    phrase = phrase.strip(" \t\n,;:.")
    if not phrase:
        return None
    if concept.get("acronym_only"):
        for tok, s, e in toks[left:right + 1]:
            clean = _tok_clean(tok)
            if clean.isupper() and 2 <= len(clean) <= 10:
                return clean
        return phrase
    return phrase


VAGUE_MODIFIERS = {"different", "next", "each", "same", "one", "another",
                   "other", "such", "first", "second", "third", "last",
                   "final", "remaining", "whole", "entire", "above",
                   "following", "previous", "many", "few", "several"}


def _phrase_score(phrase):
    """名称型短语质量分：专有名词/缩写加分，小写泛词扣分。"""
    toks = [t for t in (_tok_clean(x) for x in phrase.split()) if t]
    toks = [t for t in toks if t]
    if not toks:
        return -99.0
    name_like = sum(1 for t in toks if _is_name_like(t))
    acronym = sum(1 for t in toks if t.isupper() and len(t) >= 2)
    generic = sum(1 for t in toks if not _is_name_like(t))
    vague = sum(1 for t in toks if t.lower() in VAGUE_MODIFIERS)
    return (2.0 * name_like + 1.5 * acronym - 0.6 * generic - 1.2 * vague
            + 0.05 * len(toks))


def _best_name_value(sent_text, anchor_hits, concept):
    """句内多个概念词命中里，挑质量最高的名词短语。"""
    best, best_score = None, -99.0
    for term, _cnt, start, end, _acr in anchor_hits[:5]:
        phrase = _extract_name_value(sent_text, term, end, concept)
        if not phrase:
            continue
        sc = _phrase_score(phrase)
        if sc > best_score + 1e-9 or (abs(sc - best_score) < 1e-9 and best
                                      and len(phrase) > len(best)):
            best, best_score = phrase, sc
    return best


# ------------------------------------------------------------------ 引文处理
def _quote_window(sent, focus_start=None, focus_end=None, max_len=360):
    """从句子里切一段逐字连续、尽量不含换行的引文。"""
    text = sent["text"]
    if "\n" not in text:
        return text if len(text) <= max_len * 2 else text
    if focus_start is None:
        focus_start, focus_end = 0, len(text)
    # 找包含焦点且不含换行的最大窗口
    lo = focus_start
    while lo > 0 and text[lo - 1] != "\n":
        lo -= 1
    hi = focus_end
    while hi < len(text) and text[hi] != "\n":
        hi += 1
    window = text[lo:hi]
    if len(window) < 12:
        window = text.strip()
    return window


def _verify_quote(quote, unit_text):
    """引文必须是原文连续子串（逐字；仅允许尾部空白差异）。"""
    if not quote:
        return False
    if quote in unit_text:
        return True
    return quote.strip() in unit_text


def _unit_text_map(doc):
    return {u["id"]: u.get("text", "") for u in doc.get("units", []) if u.get("id")}


# ------------------------------------------------------------------ 主流程
def extract_field(field, sentences, lex, units=None, min_score=None):
    """对单个 field_id 做概念归一 → 检索 → 取值 → 自检。"""
    units = units or {}
    min_score = lex.get("min_score", 2.0) if min_score is None else min_score
    fid = field.get("field_id")
    desc = field.get("description", "")
    concept_name, conf, concept_hits = classify_field(field, lex)
    concept = lex.get("concepts", {}).get(concept_name, {})
    ctype = concept.get("type", "name")
    anchor_terms, support_terms = _concept_terms(concept, lex)
    field_terms = tokenize(field.get("_text") or desc)

    if concept_name == "general" or not anchor_terms:
        # 没有概念锚点：只接受字段原文词全部命中的强证据（合成字段直接 not_reported）
        rows = []
        for s in sentences:
            low = s["text"].lower()
            if field_terms and all(_contains(low, t.lower()) for t in field_terms):
                sc, hits, _n = score_sentence(s, [], [], field_terms, concept, lex)
                rows.append((sc + 3.0, s, hits))
        rows.sort(key=lambda x: -x[0])
        if not rows:
            return _row(field, STATUS_NOT_REPORTED, concept_name, conf,
                         note="字段描述未能归一到任何概念类别，且原文没有与描述词全部共现的句子；"
                              "按契约记为 not_reported（缺失不等于 0，不填推测值）。")
        sc, s, hits = rows[0]
        low = s["text"].lower()
        pos = 0
        for t in field_terms:
            p = low.find(t.lower())
            if p >= 0:
                pos = p + len(t)
                break
        val = _extract_name_value(s["text"], None, pos, concept)
        return _finish(field, s, val, None, None, concept_name, conf, lex,
                       note="字段未归一到已知概念，按字面共现给出候选，请复核取值语义。")

    scored = []
    for s in sentences:
        if s.get("kind") == "references":
            continue  # 参考文献条目不能用来回答「本文用了什么」
        sc, hits, n_anchor = score_sentence(s, anchor_terms, support_terms,
                                             field_terms, concept, lex)
        if sc <= 0 or n_anchor == 0:
            # 数值型字段必须有「概念词 + 数值」的锚定关系，光有支持词不算证据
            continue
        scored.append((sc, s, hits, n_anchor))

    # 先抽值再排序：值的「形态质量」参与打分（专有名词优于泛指词），
    # 「声明句式」也算证据（"We used the X to evaluate ..."）。
    prepared = []
    for sc, s, hits, _n_anchor in scored:
        nums = _numbers_in_sentence(s["text"], lex.get("unit_whitelist", []))
        best_num = _pick_number(s["text"], anchor_terms, nums, concept_name)
        value, unit, focus = None, None, None
        if ctype == "number":
            if best_num:
                value = best_num["raw"]
                unit = best_num["unit"] or None
                focus = (best_num["start"], best_num["end"])
        else:
            ahits = _anchor_hits(s["text"], anchor_terms)
            if ahits:
                value = _best_name_value(s["text"], ahits, concept)
                if value:
                    pos = s["text"].find(value)
                    focus = (pos, pos + len(value)) if pos >= 0 else None
        bonus = 0.0
        if value:
            if ctype == "number":
                bonus += 0.3
            else:
                bonus += min(2.0, 0.3 * max(0.0, _phrase_score(value)))
        low = s["text"].lower()
        decl_bonus = 0.0
        for decl in concept.get("declare", []):
            if _contains(low, decl):
                decl_bonus += 0.8
        bonus += min(1.6, decl_bonus)
        prepared.append((sc + bonus, s, hits, value, unit, focus))
    # 有概念词命中的句子优先；同等分数取靠前的句子
    prepared.sort(key=lambda x: (-x[0], x[1]["page"] or 0, x[1]["sentence"]))

    candidates = []
    for sc, s, hits, value, unit, focus in prepared[:6]:
        quote = _quote_window(s, focus[0] if focus else None,
                              focus[1] if focus else None)
        candidates.append({
            "quote": quote,
            "paragraph_id": s["anchor"],
            "score": round(float(sc), 2),
            "matched_terms": hits[:8],
            "value": value,
            "unit": unit,
        })

    if not prepared:
        return _row(field, STATUS_NOT_REPORTED, concept_name, conf,
                    note="原文没有出现与该概念（%s）相关的表述，按契约记为 not_reported；"
                         "不以 0、空串或推测值填充。" % concept.get("label", concept_name))

    best_score, best_sent, _hits, _value, _unit, _focus = prepared[0]
    best_cand = candidates[0]
    value = best_cand["value"]
    if not value:
        return _row(field, STATUS_NOT_REPORTED, concept_name, conf,
                    candidates=candidates,
                    note="命中最相关句子（%s）但该句没有给出可用取值，"
                         "按契约记为 not_reported。" % concept.get("label", concept_name))

    # ---- 自检：引文逐字 + value 是引文的子串 ----
    unit_text = units.get(best_sent["section"], "")
    quote = best_cand["quote"]
    if not _verify_quote(quote, unit_text):
        quote = best_sent["text"]
        best_cand["quote"] = quote
        if not _verify_quote(quote, unit_text):
            return _row(field, STATUS_NOT_REPORTED, concept_name, conf,
                        candidates=candidates,
                        note="候选引文无法在锚点章节内逐字复核，按契约降级为 not_reported。")
    if value not in quote:
        # 尝试重新定位：把 value 在句中的位置换算成引文内的相对位置
        rel = best_sent["text"].find(value)
        if rel >= 0 and rel + len(value) <= len(quote):
            pass
        else:
            return _row(field, STATUS_NOT_REPORTED, concept_name, conf,
                        candidates=candidates,
                        note="取值不在逐字引文内（不换算、不改写），按契约降级为 not_reported。")

    # ---- 冲突检测：只有两处真的互斥才 source_conflict ----
    conflict = _detect_conflict(candidates, concept, ctype)
    if conflict:
        return _row(field, STATUS_CONFLICT, concept_name, conf,
                    candidates=candidates,
                    note="原文在两处给出互斥表述：%s。已在 candidates 列出两处逐字引文，"
                         "value/quote 留空，等待人工判定口径。" % " / ".join(conflict))

    stat = _statistic_of(concept_name, value, quote, ctype)
    cond = _condition_of(best_sent["text"], value, concept, ctype, concept_name)
    comp = _comparator_of(best_sent["text"], concept_name, value)
    return _finish_row(field, best_sent, best_cand, value, stat, cond, comp,
                       concept_name, conf, lex, candidates)


def _detect_conflict(candidates, concept, ctype):
    """两处互斥原文才判 source_conflict（保守：拿不准就降级为 reported）。"""
    if ctype != "number" or len(candidates) < 2:
        return []
    vals = []
    for c in candidates[:3]:
        v = c.get("value")
        if v and v not in [x[0] for x in vals]:
            vals.append((v, c))
    if len(vals) < 2:
        return []
    (v1, c1), (v2, c2) = vals[0], vals[1]
    if c1["paragraph_id"] == c2["paragraph_id"]:
        return []
    if c1["score"] - c2["score"] > 1.0:
        return []
    # 必须有对比/矛盾信号，否则只是不同配置下的不同取值
    text1 = c1["quote"].lower()
    text2 = c2["quote"].lower()
    if not (CONTRAST_RE.search(text1) or CONTRAST_RE.search(text2)):
        return []
    return ["%s（%s）" % (v1, c1["paragraph_id"]), "%s（%s）" % (v2, c2["paragraph_id"])]


def _statistic_of(concept_name, value, quote, ctype):
    """statistic：指标/统计量名（逐字取自引文）。"""
    if concept_name in ("metric", "metric_value", "statistic", "result_value"):
        if not value:
            return None
        if concept_name == "metric":
            # 指标全称，例如 "cased BLEU score"
            m = re.search(r"((?:[A-Za-z][A-Za-z\-]{0,14}\s+){0,2})" +
                           re.escape(value) + r"(\s+[A-Za-z][A-Za-z\-]{0,14})?",
                           quote)
            if m:
                frag = re.sub(r"\s+", " ", m.group(0)).strip()
                parts = frag.split(" ", 1)
                if len(parts) == 2 and _tok_clean(parts[0]).lower() in DETERMINERS:
                    frag = parts[1].lstrip()
                if frag:
                    return frag
        if value in quote:
            return value
    return None


CONDITION_CONCEPTS = ("result_value", "metric_value", "metric", "baseline",
                      "ablation", "statistic", "experimental_condition")


def _condition_of(sent_text, value, concept, ctype, concept_name=""):
    """experimental_condition：取值成立的条件（原文短语，不臆造）。"""
    if concept_name and concept_name not in CONDITION_CONCEPTS:
        return None
    low = (sent_text or "").lower()
    pats = [r"\bon\s+(?:the\s+)?([A-Za-z0-9''\- ]{3,60}?\b(?:set|test|train\w*|"
            r"validation|dev)\b)",
            r"\bfor\s+(?:the\s+)?([A-Za-z0-9''\- ]{3,60}?\b(?:set|test|train\w*|"
            r"validation|dev)\b)",
            r"\b(ensemble of [^.,;]{3,60})",
            r"\b([A-Za-z0-9''\- ]*?(?:ntst\d*|ntest\d*|WMT''?\d{2}))"]
    for pat in pats:
        m = re.search(pat, sent_text)
        if not m:
            continue
        frag = re.sub(r"\s+", " ", m.group(1)).strip(" .,:;")
        if len(frag) < 4:
            continue
        return frag[:160]
    return None


COMPARATOR_OBJ_RE = re.compile(
    r"\b(?:compared\s+(?:to|with)|versus|vs\.?|relative\s+to|against|"
    r"over\s+the\s+baseline)\s+(?:the\s+|a\s+|an\s+)?([A-Za-z0-9''\- ]{2,60})",
    re.I)


def _comparator_of(sent_text, concept_name="", value=None):
    """comparator：明确写出来的「对比对象」；不做推断。"""
    m = COMPARATOR_OBJ_RE.search(sent_text or "")
    if m:
        frag = re.sub(r"\s+", " ", m.group(1)).strip(" .,:;")
        if frag and frag.lower() not in ("it", "them", "this", "that"):
            return frag[:120]
    if concept_name == "comparator":
        return None
    return None


def _row(field, status, concept_name, conf, candidates=None, note=""):
    row = {
        "field_id": field.get("field_id"),
        "description": field.get("description", ""),
        "status": status,
        "value": None,
        "unit": None,
        "statistic": None,
        "experimental_condition": None,
        "comparator": None,
        "quote": None,
        "paragraph_id": None,
        "candidates": candidates or [],
        "notes": note,
        "note": note,
        "needs_review": False,
        "review": {"by": "script", "confidence": 0.0, "basis": concept_name},
    }
    return row


def _finish_row(field, sent, cand, value, stat, cond, comp, concept_name,
                conf, lex, candidates):
    row = _row(field, STATUS_REPORTED, concept_name, conf, candidates=candidates)
    row["value"] = value
    row["unit"] = cand.get("unit")
    row["statistic"] = stat
    row["experimental_condition"] = cond
    row["comparator"] = comp
    row["quote"] = cand["quote"]
    row["paragraph_id"] = cand["paragraph_id"]
    score = cand.get("score", 0.0)
    label = lex.get("concepts", {}).get(concept_name, {}).get("label", concept_name)
    row["review"] = {
        "by": "script",
        "confidence": round(min(0.95, 0.35 + score / 12.0), 2),
        "basis": "概念=%s；引文逐字命中锚点章节；value 为引文连续子串" % label,
    }
    matched = cand.get("matched_terms") or []
    row["notes"] = ("概念归一：%s（命中 %s）；引文逐字取自 %s；取值按该概念的形态规则截取，"
                    "未换算、未改写。" % (
                        label,
                        ", ".join(matched[:4]) or "-",
                        cand["paragraph_id"]))
    row["note"] = row["notes"]
    return row


def _finish(field, sent, value, unit, stat, concept_name, conf, lex, note=""):
    row = _row(field, STATUS_REPORTED, concept_name, conf, note=note)
    if value:
        row["value"] = value
        row["quote"] = sent["text"]
        row["paragraph_id"] = sent["anchor"]
        row["review"] = {"by": "script", "confidence": 0.4, "basis": "字面共现"}
    return row


def build_review_sheet(rows, max_chars=190):
    """紧凑复核表：供模型/人工可选抽检（整体 < 3000 token）。"""
    sheet = []
    for r in rows:
        quote = r.get("quote") or ""
        if len(quote) > max_chars:
            quote = quote[:max_chars].rstrip() + "…"
        sheet.append({
            "field_id": r.get("field_id"),
            "status": r.get("status"),
            "value": r.get("value"),
            "unit": r.get("unit"),
            "statistic": r.get("statistic"),
            "experimental_condition": r.get("experimental_condition"),
            "comparator": r.get("comparator"),
            "paragraph_id": r.get("paragraph_id"),
            "quote": quote,
            "alternatives": [c.get("value") for c in (r.get("candidates") or [])[1:4]],
        })
    return sheet


def _fnum(text):
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text or "")
    return float(m.group(0)) if m else None


def _figure_row(field, status, value=None, quote=None, anchor=None,
                unit=None, note="", confidence=0.8):
    row = _row(field, status, "figure_structure", confidence)
    row.update({"value": value, "quote": quote, "paragraph_id": anchor,
                "unit": unit, "notes": note, "note": note})
    row["review"] = {"by": "script", "confidence": confidence,
                     "basis": note or "图表结构（坐标轴/表格/图注）直接取值"}
    return row


def _axis_figure_row(field, doc):
    desc = (field.get("description") or "").lower()
    if not re.search(r"axis|轴|坐标", desc):
        return None
    if not re.search(r"unit|单位|量纲|scale|type|log|linear|刻度|量级|类型|标签|label",
                     desc):
        return None
    side = None
    if re.search(r"\bx[\s_-]?axis\b|横轴|x\s*轴|x轴", desc):
        side = "x"
    elif re.search(r"\by[\s_-]?axis\b|纵轴|y\s*轴|y轴", desc):
        side = "y"
    if re.search(r"unit|单位|量纲", desc):
        attr = "unit"
    elif re.search(r"scale|type|log|linear|刻度|量级|类型", desc):
        attr = "scale"
    else:
        attr = "label"
    for ax in doc.get("axes") or []:
        if side and str(ax.get("axis", "")).lower() != side:
            continue
        value = ax.get(attr)
        if value in (None, "", "not_reported"):
            continue
        value = str(value)
        quote = ax.get("quote") or ""
        if value.lower() not in quote.lower():
            continue
        return _figure_row(
            field, "reported", value, quote, ax.get("anchor"),
            unit=ax.get("unit") if attr == "unit" else None,
            note="从坐标轴文本声明取值（axis=%s, attr=%s）；未做像素刻度读数"
                 % (ax.get("axis"), attr))
    return None


def _caption_sample_size(field, doc):
    desc = (field.get("description") or "").lower()
    if not re.search(r"sample size|\bn\b|样本量|重复数|动物数|细胞数|例子数", desc):
        return None
    for cap in doc.get("captions") or []:
        if cap.get("n") is None:
            continue
        quote = cap.get("text") or ""
        value = str(cap["n"])
        if value not in quote:
            continue
        return _figure_row(field, "reported", value, quote, cap.get("anchor"),
                           unit="n", note="图注/表注明确给出的样本量（逐字引文含 n = %s）" % value)
    return None


def _pick_header_index(header, desc):
    if re.search(r"significan|显著性|\bp\s*value|p值|星号", desc):
        want = "significance"
    elif re.search(r"error|误差|s\.?e\.?m|s\.?d\.?|error bar", desc):
        want = "error"
    else:
        want = None
    if want:
        for h in header:
            if h.get("role") == want:
                return h["index"] - 1
    words = {w for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", desc)
             if w.lower() not in ("the", "and", "for", "with", "value", "from")}
    for h in header:
        if h.get("role") == "x_axis":
            continue
        name = (h.get("name") or "").lower()
        if any(w.lower() in name for w in words):
            return h["index"] - 1
    for h in header:
        if h.get("role") == "y_axis":
            return h["index"] - 1
    return None


def _table_figure_row(field, doc):
    desc = field.get("description") or ""
    low = desc.lower()
    if not doc.get("tables"):
        return None
    target = _fnum(desc)
    for t in doc["tables"]:
        header = t.get("header") or []
        rows = t.get("rows") or []
        if not header or not rows:
            continue
        idx = _pick_header_index(header, low)
        if idx is None:
            continue
        xidx = next((h["index"] - 1 for h in header if h.get("role") == "x_axis"), None)
        for row in rows:
            cells = row.get("cells") or []
            if idx >= len(cells) or not str(cells[idx]).strip():
                continue
            if target is not None:
                if xidx is not None and xidx < len(cells):
                    if _fnum(cells[xidx]) != target:
                        continue
                elif target not in [c for c in (_fnum(x) for x in cells) if c is not None]:
                    continue
            value = str(cells[idx]).strip()
            quote = row.get("row_quote") or ""
            if value not in quote:
                continue
            return _figure_row(
                field, "reported", value, quote, row.get("page_anchor"),
                unit=header[idx].get("unit"),
                note="从表格 %s 第 %s 行按列「%s」取值；行引文逐字保留"
                     % (t.get("id"), row.get("row"), header[idx].get("name")))
    return None


def _tick_figure_row(field, doc):
    desc = (field.get("description") or "").lower()
    if not re.search(r"tick|刻度值|刻度起点|刻度间隔|tick label", desc):
        return None
    return _figure_row(
        field, "not_reported", None, None, None,
        note="刻度值需要像素级读数/OCR；本 Skill 不做图像像素读取，按 not_reported 处理，不臆造刻度")


def figure_field_row(field, doc):
    """图表结构可确定回答的字段优先走这里；不匹配返回 None 交给通用抽取。"""
    for fn in (_axis_figure_row, _caption_sample_size, _tick_figure_row,
               _table_figure_row):
        try:
            row = fn(field, doc)
        except Exception:
            row = None
        if row is not None:
            return row
    return None


def run(input_dir, doc, work_dir):
    """按字段表抽取，返回 {fields, review_sheet, meta}。"""
    spec, spec_path = load_target_fields(input_dir)
    lex = load_lexicon()
    out = {
        "target_fields_source": spec_path,
        "status": STATUS_FAILED if spec is None else "ok",
        "fields": [],
        "review_sheet": [],
        "meta": {},
    }
    if spec is None:
        out["note"] = ("未找到 target-fields.json；无法按字段表驱动抽取。"
                       "请确认案例是否提供该输入，或改用通用解析路径。")
        out["meta"] = {"error": "target fields not found", "input_dir": input_dir}
        return out

    fields = normalize_fields(spec)
    sentences = _sentences(doc)
    units = _unit_text_map(doc)
    rows = []
    for f in fields:
        try:
            row = figure_field_row(f, doc)
            if row is None:
                row = extract_field(f, sentences, lex, units)
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            row = _row(f, STATUS_FAILED, "general", 0.0,
                       note="抽取过程异常（%s），记为 extraction_failed，需人工接管。" % exc)
            rows.append(row)

    out["fields"] = rows
    out["review_sheet"] = build_review_sheet(rows)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    out["meta"] = {
        "field_count": len(rows),
        "status_counts": counts,
        "sentences_scanned": len(sentences),
        "lexicon_version": lex.get("version"),
        "source": "script",
        "review_mode": "语义判定由脚本完成，模型复核为可选",
    }
    return out


# ------------------------------------------------------------------- CLI
def _find_document(input_dir):
    """在输入目录里找主文档（没有 --doc 时用）。"""
    skip = {"task.md", "readme.md", "case.json", "challenge.json"}
    for dirpath, dirnames, filenames in os.walk(input_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.lower() in skip or name.startswith("."):
                continue
            if name.lower().endswith((".pdf", ".tex", ".docx", ".md", ".txt")):
                return os.path.join(dirpath, name)
    return None


def _load_doc(doc_path, input_dir, work_dir):
    if doc_path and os.path.isfile(doc_path):
        with open(doc_path, "r", encoding="utf-8") as fh:
            return json.load(fh), doc_path
    primary = _find_document(input_dir)
    if not primary:
        return {}, None
    import doc_extract
    outdir = os.path.join(work_dir or ".", "_extract")
    os.makedirs(outdir, exist_ok=True)
    doc = doc_extract.build_doc(primary, outdir)
    path = os.path.join(work_dir or ".", "doc.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
    except OSError:
        pass
    return doc, path


def main(argv=None):
    ap = argparse.ArgumentParser(description="按目标字段表抽取")
    ap.add_argument("--input", default="/input")
    ap.add_argument("--doc", help="doc_extract.py 产出的 doc.json（缺省则从 --input 现场抽取）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mark-review-required", action="store_true",
                    help="退回旧行为：每行标 needs_review=true，交由上层语义复核")
    args = ap.parse_args(argv)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    doc, doc_path = _load_doc(args.doc, args.input, out_dir)
    if not doc:
        result = {"fields": [], "review_sheet": [], "status": STATUS_FAILED,
                  "meta": {"error": "document not readable"}}
    else:
        result = run(args.input, doc, out_dir)
    if args.mark_review_required:
        for row in result.get("fields", []):
            row["needs_review"] = True
            row.setdefault("review", {})["by"] = "candidate"
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("fields=%d status=%s doc=%s -> %s" % (
        len(result.get("fields", [])), result.get("status"), doc_path, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
