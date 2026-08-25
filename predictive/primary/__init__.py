"""
Primary growth models.

Distinct from predictive/engines/, which implements ComBase's *secondary*
model (environment -> mu_max). This package implements *primary* models
(population over time, given a rate) -- currently just Baranyi-Roberts.
The two compose (a secondary model's mu_max feeds a primary model as one
input) but neither depends on the other's code.
"""
