"""EHR feature catalog and coming-soon messaging."""
from __future__ import annotations

from app.schemas.ehr_sync import EhrFeatureOut

EHR_COMING_SOON_MESSAGE = (
    "EHR synchronization is coming soon. You can preview settings now, but live sync is not available yet."
)

EHR_FEATURES: list[EhrFeatureOut] = [
    EhrFeatureOut(
        id="patient_sync",
        label="Patient & appointment sync",
        description="Import and keep patients and appointments in sync with your health record system.",
        status="coming_soon",
    ),
    EhrFeatureOut(
        id="insertion_rules",
        label="Insertion rules (write to EHR)",
        description="Write procedure codes and visit types into your health record when patients book online or claim waitlist slots.",
        status="coming_soon",
    ),
    EhrFeatureOut(
        id="mapping_rules",
        label="Mapping rules (read from EHR)",
        description="Tag EHR appointments by visit type, procedure code, provider, or operatory for communications and forms.",
        status="coming_soon",
    ),
    EhrFeatureOut(
        id="form_sync",
        label="Form sync to EHR",
        description="Push completed patient forms into the patient chart in your health record system.",
        status="coming_soon",
    ),
    EhrFeatureOut(
        id="waitlist_recall",
        label="Waitlist recall lists",
        description="Build waitlist requests from recall and continuing-care lists in your EHR.",
        status="coming_soon",
    ),
    EhrFeatureOut(
        id="medical_alerts",
        label="Medical alerts from EHR",
        description="Read medical history alert catalogs directly from your health record system.",
        status="coming_soon",
    ),
]
