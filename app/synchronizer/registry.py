"""Registry of EHR system adapters."""
from __future__ import annotations

from app.models.practice import EhrSystem
from app.synchronizer.types import EhrAdapter
from app.synchronizer.dentrix import DentrixAdapter
from app.synchronizer.fhir import FhirAdapter
from app.synchronizer.open_dental import OpenDentalAdapter
from app.synchronizer.other import OtherEhrAdapter

_ADAPTERS: dict[EhrSystem, EhrAdapter] = {
    EhrSystem.OPEN_DENTAL: OpenDentalAdapter(),
    EhrSystem.DENTRIX: DentrixAdapter(),
    EhrSystem.ATHENA: FhirAdapter(EhrSystem.ATHENA),
    EhrSystem.ECLINICALWORKS: FhirAdapter(EhrSystem.ECLINICALWORKS),
    EhrSystem.EPIC: FhirAdapter(EhrSystem.EPIC),
    EhrSystem.OTHER: OtherEhrAdapter(),
}


def get_adapter(ehr_system: EhrSystem) -> EhrAdapter:
    if ehr_system == EhrSystem.NONE:
        raise ValueError("No EHR system selected")
    adapter = _ADAPTERS.get(ehr_system)
    if adapter is None:
        return OtherEhrAdapter()
    return adapter
