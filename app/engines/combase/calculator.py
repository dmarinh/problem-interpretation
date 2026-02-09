"""
ComBase Calculator

Implements the polynomial equation for calculating mu (growth rate)
and doubling time from environmental parameters.

Based on the ComBase broth model equations:
- Growth (ModelID=1): mu = exp(polynomial), bw = sqrt(1 - aw)
- Thermal Inactivation (ModelID=2): mu = -exp(polynomial), bw = aw
- Non-thermal Survival (ModelID=3): mu = -exp(polynomial), bw = sqrt(1 - aw)

The polynomial equation:
    ln(mu) = b0 + b1*T + b2*pH + b3*bw + b4*T*pH + b5*T*bw + b6*pH*bw
           + b7*T² + b8*pH² + b9*bw² + b10*F4 + b11*T*F4 + b12*pH*F4
           + b13*bw*F4 + b14*F4²

Where:
    T = temperature (°C)
    pH = pH value
    bw = water activity term (model-dependent)
    F4 = fourth factor value (0 if not applicable)
    b0-b14 = model coefficients
"""

import math
from dataclasses import dataclass

from app.engines.combase.models import ComBaseModel
from app.models.enums import ModelType, Factor4Type


@dataclass
class CalculationResult:
    """Result of a ComBase calculation."""
    mu_max: float  # Maximum specific growth rate (1/h or log10 CFU/h)
    doubling_time_hours: float | None  # Doubling time (hours), None for inactivation
    ln_mu: float  # Natural log of mu (intermediate value)
    
    # Inputs used
    temperature: float
    ph: float
    aw: float
    bw: float  # Water activity term used in calculation
    factor4_value: float
    
    # Model info
    model_type: ModelType
    organism_id: str
    
    # Validation
    within_range: bool  # Whether all inputs were within valid range
    warnings: list[str]


class ComBaseCalculator:
    """
    Calculator for ComBase broth models.
    
    Usage:
        calculator = ComBaseCalculator(model)
        result = calculator.calculate(temperature=25.0, ph=7.0, aw=0.99)
    """
    
    # Natural log of 2, used for doubling time calculation
    LN2 = math.log(2)
    
    def __init__(self, model: ComBaseModel):
        """
        Initialize calculator with a specific model.
        
        Args:
            model: ComBaseModel with coefficients and constraints
        """
        self.model = model
        self.coefficients = model.coefficients
        self.constraints = model.constraints
    
    def calculate(
        self,
        temperature: float,
        ph: float,
        aw: float,
        factor4_value: float = 0.0,
        clamp_to_range: bool = False,
    ) -> CalculationResult:
        """
        Calculate mu (growth rate) and doubling time.
        
        Args:
            temperature: Temperature in Celsius
            ph: pH value
            aw: Water activity (0-1)
            factor4_value: Fourth factor value (0 if not applicable)
            clamp_to_range: Whether to clamp inputs to valid range
            
        Returns:
            CalculationResult with mu, doubling time, and metadata
        """
        warnings = []
        within_range = True
        
        # Always validate range
        if not self.constraints.is_temperature_valid(temperature):
            within_range = False
            if clamp_to_range:
                warnings.append(f"Temperature {temperature}°C clamped to [{self.constraints.temp_min}, {self.constraints.temp_max}]")
                temperature = self.constraints.clamp_temperature(temperature)
            else:
                warnings.append(f"Temperature {temperature}°C outside valid range [{self.constraints.temp_min}, {self.constraints.temp_max}]")
        
        if not self.constraints.is_ph_valid(ph):
            within_range = False
            if clamp_to_range:
                warnings.append(f"pH {ph} clamped to [{self.constraints.ph_min}, {self.constraints.ph_max}]")
                ph = self.constraints.clamp_ph(ph)
            else:
                warnings.append(f"pH {ph} outside valid range [{self.constraints.ph_min}, {self.constraints.ph_max}]")
        
        if not self.constraints.is_aw_valid(aw):
            within_range = False
            if clamp_to_range:
                warnings.append(f"Water activity {aw} clamped to [{self.constraints.aw_min}, {self.constraints.aw_max}]")
                aw = self.constraints.clamp_aw(aw)
            else:
                warnings.append(f"Water activity {aw} outside valid range [{self.constraints.aw_min}, {self.constraints.aw_max}]")
        
        if self.model.factor4_type != Factor4Type.NONE and not self.constraints.is_factor4_valid(factor4_value):
            within_range = False
            if clamp_to_range:
                warnings.append(f"Factor4 {factor4_value} clamped to [{self.constraints.factor4_min}, {self.constraints.factor4_max}]")
                factor4_value = self.constraints.clamp_factor4(factor4_value)
            else:
                warnings.append(f"Factor4 {factor4_value} outside valid range [{self.constraints.factor4_min}, {self.constraints.factor4_max}]")
        
        # Calculate bw (water activity term) based on model type
        bw = self._calculate_bw(aw)
        
        # Calculate ln(mu) using polynomial
        ln_mu = self._calculate_ln_mu(temperature, ph, bw, factor4_value)
        
        # Calculate mu based on model type
        mu_max = self._calculate_mu(ln_mu)
        
        # Calculate doubling time (only for growth models with positive mu)
        doubling_time = self._calculate_doubling_time(mu_max)
        
        return CalculationResult(
            mu_max=mu_max,
            doubling_time_hours=doubling_time,
            ln_mu=ln_mu,
            temperature=temperature,
            ph=ph,
            aw=aw,
            bw=bw,
            factor4_value=factor4_value,
            model_type=self.model.model_type,
            organism_id=self.model.organism_id,
            within_range=within_range,
            warnings=warnings,
        )
    
    def _calculate_bw(self, aw: float) -> float:
        """
        Calculate the water activity term (bw) based on model type.
        
        - Growth (ModelID=1): bw = sqrt(1 - aw)
        - Thermal Inactivation (ModelID=2): bw = aw
        - Non-thermal Survival (ModelID=3): bw = sqrt(1 - aw)
        """
        if self.model.model_type == ModelType.THERMAL_INACTIVATION:
            return aw
        else:
            # Growth and Non-thermal Survival
            return math.sqrt(max(0, 1 - aw))
    
    def _calculate_ln_mu(
        self,
        tr: float,  # temperature
        pr: float,  # pH
        bw: float,  # water activity term
        ef4: float,  # factor 4
    ) -> float:
        """
        Calculate ln(mu) using the polynomial equation.
        
        ln(mu) = b0 + b1*T + b2*pH + b3*bw + b4*T*pH + b5*T*bw + b6*pH*bw
               + b7*T² + b8*pH² + b9*bw² + b10*F4 + b11*T*F4 + b12*pH*F4
               + b13*bw*F4 + b14*F4²
        """
        b = self.coefficients
        
        # Ensure we have 15 coefficients (pad with zeros if needed)
        while len(b) < 15:
            b = list(b) + [0.0]
        
        ln_mu = (
            b[0]                    # b0: intercept
            + b[1] * tr             # b1: temperature
            + b[2] * pr             # b2: pH
            + b[3] * bw             # b3: water activity term
            + b[4] * tr * pr        # b4: T * pH
            + b[5] * tr * bw        # b5: T * bw
            + b[6] * pr * bw        # b6: pH * bw
            + b[7] * tr ** 2        # b7: T²
            + b[8] * pr ** 2        # b8: pH²
            + b[9] * bw ** 2        # b9: bw²
            + b[10] * ef4           # b10: factor4
            + b[11] * tr * ef4      # b11: T * factor4
            + b[12] * pr * ef4      # b12: pH * factor4
            + b[13] * bw * ef4      # b13: bw * factor4
            + b[14] * ef4 ** 2      # b14: factor4²
        )
        
        return ln_mu
    
    def _calculate_mu(self, ln_mu: float) -> float:
        """
        Calculate mu from ln(mu) based on model type.
        
        - Growth (ModelID=1): mu = exp(ln_mu)
        - Thermal Inactivation (ModelID=2): mu = -exp(ln_mu)
        - Non-thermal Survival (ModelID=3): mu = -exp(ln_mu)
        """
        if self.model.model_type == ModelType.GROWTH:
            return math.exp(ln_mu)
        else:
            # Inactivation and Survival have negative mu
            return -math.exp(ln_mu)
    
    def _calculate_doubling_time(self, mu_max: float) -> float | None:
        """
        Calculate doubling time from mu.
        
        Only applicable for growth models with positive mu.
        Doubling time = ln(2) / mu
        
        Returns None for inactivation/survival models.
        """
        if self.model.model_type != ModelType.GROWTH:
            return None
        
        if mu_max <= 0:
            return None
        
        return self.LN2 / mu_max
    
    def calculate_log_increase(
        self,
        mu_max: float,
        duration_hours: float,
    ) -> float:
        """
        Calculate log10 CFU increase over a duration.
        
        Args:
            mu_max: Growth rate (1/h)
            duration_hours: Duration in hours
            
        Returns:
            Log10 CFU increase
        """
        if mu_max <= 0:
            # Inactivation/death
            return mu_max * duration_hours
        
        # Growth: log increase = mu * t / ln(10)
        return mu_max * duration_hours / math.log(10)
