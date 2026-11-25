# Synthetic reproduction report (not a real paper)

## Methods

We used the public dataset GSE12345 with 60 participants (n = 30 per group). All analyses were run in Python 3.9 with statsmodels 0.13.

Models were trained for 200 epochs with a learning rate of 0.001 and a batch size of 32.

The analysis script was executed as: $ python3 analysis.py --config config.yaml

## Results

Body weight decreased from 82.4 kg to 79.1 kg (4.0% reduction). The intervention reduced body weight compared with control (t(28) = 2.45, p = 0.02).

In a sensitivity analysis the effect was smaller and not significant (t(28) = 1.10, p = 0.28).

## Data availability

The analysis code is available at https://github.com/example/synthetic-repro.
