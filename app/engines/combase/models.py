"""
ComBase Model Data Structures

Represents the ComBase model definitions loaded from CSV.
Each model has coefficients and valid parameter ranges.
"""

import csv
import math
from pathlib import Path

from pydantic import BaseModel, Field

from app.models.enums import ModelType, ComBaseOrganism, Factor4Type


class ComBaseModelConstraints(BaseModel):
    """Valid parameter ranges for a ComBase model."""
    temp_min: float = Field(description="Minimum valid temperature (°C)")
    temp_max: float = Field(description="Maximum valid temperature (°C)")
    ph_min: float = Field(description="Minimum valid pH")
    ph_max: float = Field(description="Maximum valid pH")
    aw_min: float = Field(description="Minimum valid water activity")
    aw_max: float = Field(description="Maximum valid water activity")
    factor4_min: float | None = Field(default=None, description="Minimum factor4 value")
    factor4_max: float | None = Field(default=None, description="Maximum factor4 value")
    
    def is_temperature_valid(self, temp: float) -> bool:
        """Check if temperature is within valid range."""
        return self.temp_min <= temp <= self.temp_max
    
    def is_ph_valid(self, ph: float) -> bool:
        """Check if pH is within valid range."""
        return self.ph_min <= ph <= self.ph_max
    
    def is_aw_valid(self, aw: float) -> bool:
        """Check if water activity is within valid range."""
        return self.aw_min <= aw <= self.aw_max
    
    def is_factor4_valid(self, value: float) -> bool:
        """Check if factor4 value is within valid range."""
        if self.factor4_min is None or self.factor4_max is None:
            return True  # No factor4 for this model
        return self.factor4_min <= value <= self.factor4_max
    
    def clamp_temperature(self, temp: float) -> float:
        """Clamp temperature to valid range."""
        return max(self.temp_min, min(temp, self.temp_max))
    
    def clamp_ph(self, ph: float) -> float:
        """Clamp pH to valid range."""
        return max(self.ph_min, min(ph, self.ph_max))
    
    def clamp_aw(self, aw: float) -> float:
        """Clamp water activity to valid range."""
        return max(self.aw_min, min(aw, self.aw_max))
    
    def clamp_factor4(self, value: float) -> float:
        """Clamp factor4 to valid range."""
        if self.factor4_min is None or self.factor4_max is None:
            return value
        return max(self.factor4_min, min(value, self.factor4_max))


class ComBaseModelDefaults(BaseModel):
    """Default parameter values for a ComBase model."""
    temp: float = Field(description="Default temperature (°C)")
    ph: float = Field(description="Default pH")
    aw: float = Field(description="Default water activity")
    nacl: float = Field(description="Default NaCl (%)")
    factor4: float | None = Field(default=None, description="Default factor4 value")
    inoculum: float = Field(description="Default inoculum (log CFU)")


class ComBaseModel(BaseModel):
    """
    Complete ComBase model definition.
    
    Contains all information needed to run the model:
    - Identification (organism, type, factor4)
    - Coefficients for the polynomial equation
    - Valid parameter ranges
    - Default values
    """
    # Identification
    model_id: int = Field(description="ComBase ModelID (1=Growth, 2=Thermal, 3=Non-thermal)")
    organism_id: str = Field(description="Organism short code (e.g., 'lm', 'ss')")
    organism_name: str = Field(description="Full organism name")
    model_type: ModelType = Field(description="Type of model")
    factor4_type: Factor4Type = Field(default=Factor4Type.NONE, description="Fourth factor type")
    
    # Model parameters
    y_max: float = Field(description="Maximum population density")
    h0: float = Field(description="Initial physiological state")
    coefficients: list[float] = Field(description="15 polynomial coefficients")
    
    # Constraints
    constraints: ComBaseModelConstraints = Field(description="Valid parameter ranges")
    
    # Defaults
    defaults: ComBaseModelDefaults = Field(description="Default parameter values")
    
    # Error estimates
    std_err: float = Field(description="Standard error of the model")
    h0_std_err: float = Field(description="Standard error of h0")
    
    def get_unique_key(self) -> str:
        """Get unique identifier for this model."""
        return f"{self.model_id}_{self.organism_id}_{self.factor4_type.value}"


def _parse_coefficients(coeff_str: str) -> list[float]:
    """Parse coefficient string from CSV."""
    # Remove quotes and split by semicolon
    cleaned = coeff_str.strip('"').strip()
    parts = cleaned.split(";")
    return [float(p) for p in parts]


def _parse_float(value: str, default: float = 0.0) -> float:
    """Parse float from CSV, handling NULL."""
    if value is None or value.upper() == "NULL" or value.strip() == "":
        return default
    return float(value)


def _parse_optional_float(value: str) -> float | None:
    """Parse optional float from CSV."""
    if value is None or value.upper() == "NULL" or value.strip() == "":
        return None
    return float(value)


class ComBaseModelRegistry:
    """
    Registry of all available ComBase models.
    
    Loads models from CSV and provides lookup methods.
    """
    
    def __init__(self):
        self._models: dict[str, ComBaseModel] = {}
        self._by_organism: dict[ComBaseOrganism, list[ComBaseModel]] = {}
        self._by_type: dict[ModelType, list[ComBaseModel]] = {}
    
    def load_from_csv(self, csv_path: Path) -> int:
        """
        Load models from CSV file.
        
        Args:
            csv_path: Path to the ComBase models CSV
            
        Returns:
            Number of models loaded
        """
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            
            for row in reader:
                # Skip empty rows
                if not row.get("ModelID"):
                    continue
                
                try:
                    model = self._parse_row(row)
                    self._register_model(model)
                except Exception as e:
                    # Log and skip invalid rows
                    print(f"Warning: Failed to parse row: {row.get('Org', 'unknown')} - {e}")
                    continue
        
        return len(self._models)
    
    def _parse_row(self, row: dict) -> ComBaseModel:
        """Parse a CSV row into a ComBaseModel."""
        model_id = int(row["ModelID"])
        model_type = ModelType.from_model_id(model_id)
        factor4_type = Factor4Type.from_string(row.get("Factor4ID"))
        
        constraints = ComBaseModelConstraints(
            temp_min=_parse_float(row["TempMin"]),
            temp_max=_parse_float(row["TempMax"]),
            ph_min=_parse_float(row["PHMin"]),
            ph_max=_parse_float(row["PHMax"]),
            aw_min=_parse_float(row["AwMin"]),
            aw_max=_parse_float(row["AwMax"]),
            factor4_min=_parse_optional_float(row.get("Factor4Min")),
            factor4_max=_parse_optional_float(row.get("Factor4Max")),
        )
        
        defaults = ComBaseModelDefaults(
            temp=_parse_float(row["DefaultTemp"], 20.0),
            ph=_parse_float(row["DefaultPH"], 7.0),
            aw=_parse_float(row["DefaultAw"], 0.997),
            nacl=_parse_float(row["DefaultNaCl"], 0.5),
            factor4=_parse_optional_float(row.get("DefaultFactor4")),
            inoculum=_parse_float(row["DefaultInoc"], 3.0),
        )
        
        return ComBaseModel(
            model_id=model_id,
            organism_id=row["OrganismID"].strip(),
            organism_name=row["Org"].strip(),
            model_type=model_type,
            factor4_type=factor4_type,
            y_max=_parse_float(row["ymax"]),
            h0=_parse_float(row["h0"]),
            coefficients=_parse_coefficients(row["Coefficients"]),
            constraints=constraints,
            defaults=defaults,
            std_err=_parse_float(row["StdErr"], 0.3),
            h0_std_err=_parse_float(row["H0StdErr"], 0.5),
        )
    
    def _register_model(self, model: ComBaseModel) -> None:
        """Add a model to the registry."""
        key = model.get_unique_key()
        self._models[key] = model
        
        # Index by organism
        organism = ComBaseOrganism.from_string(model.organism_id)
        if organism:
            if organism not in self._by_organism:
                self._by_organism[organism] = []
            self._by_organism[organism].append(model)
        
        # Index by type
        if model.model_type not in self._by_type:
            self._by_type[model.model_type] = []
        self._by_type[model.model_type].append(model)
    
    def get_model(
        self,
        organism: ComBaseOrganism,
        model_type: ModelType,
        factor4_type: Factor4Type = Factor4Type.NONE,
    ) -> ComBaseModel | None:
        """
        Get a specific model by organism, type, and factor4.
        
        Args:
            organism: Target organism
            model_type: Type of model
            factor4_type: Fourth factor type
            
        Returns:
            ComBaseModel or None if not found
        """
        model_id = {
            ModelType.GROWTH: 1,
            ModelType.THERMAL_INACTIVATION: 2,
            ModelType.NON_THERMAL_SURVIVAL: 3,
        }.get(model_type, 1)
        
        key = f"{model_id}_{organism.value}_{factor4_type.value}"
        return self._models.get(key)
    
    def get_models_for_organism(self, organism: ComBaseOrganism) -> list[ComBaseModel]:
        """Get all models for an organism."""
        return self._by_organism.get(organism, [])
    
    def get_models_by_type(self, model_type: ModelType) -> list[ComBaseModel]:
        """Get all models of a specific type."""
        return self._by_type.get(model_type, [])
    
    def list_organisms(self) -> list[ComBaseOrganism]:
        """List all organisms with available models."""
        return list(self._by_organism.keys())
    
    def list_all_models(self) -> list[ComBaseModel]:
        """List all loaded models."""
        return list(self._models.values())
    
    def __len__(self) -> int:
        return len(self._models)