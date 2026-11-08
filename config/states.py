"""
Official state-wise SCERT / Education Department URLs, aliases, and Hindi names for NMMS
Tracks exclusively: Bihar, UP, MP, Rajasthan, Haryana, Delhi, Jharkhand, CG, HP, UK (+ Central NSP)
"""

import os
from typing import List

# Target states strictly tracked: 10 states + CENTRAL
TARGET_STATES: List[str] = [
    "Bihar", "Uttar Pradesh", "Madhya Pradesh", "Rajasthan", "Haryana",
    "Delhi", "Jharkhand", "Chhattisgarh", "Himachal Pradesh", "Uttarakhand"
]
TARGET_STATES_AND_CENTRAL: List[str] = ["CENTRAL"] + TARGET_STATES

# Official extra vendor / third-party domains explicitly whitelisted
# Empty by default. User can configure or add verified domains here.
OFFICIAL_EXTRA_DOMAINS: List[str] = [
    d.strip().lower() for d in os.getenv("OFFICIAL_EXTRA_DOMAINS", "").split(",") if d.strip()
]

STATE_CONFIG = {
    "Bihar": {
        "authority": "SCERT Bihar",
        "official_url": "https://scert.bihar.gov.in",
        "alias": "Bihar",
        "hindi_name": "बिहार",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय", "मेधा छात्रवृत्ति"]
    },
    "Uttar Pradesh": {
        "authority": "Exam Regulatory Authority UP / SCERT UP",
        "official_url": "https://entdata.co.in",
        "alias": "UP",
        "hindi_name": "उत्तर प्रदेश",
        "keywords": ["NMMS", "NMMSS", "NMMSE", "National Means", "राष्ट्रीय आय", "entdata"]
    },
    "Rajasthan": {
        "authority": "Shala Darpan / SCERT Rajasthan",
        "official_url": "https://rajshaladarpan.nic.in",
        "alias": "Rajasthan",
        "hindi_name": "राजस्थान",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय"]
    },
    "Madhya Pradesh": {
        "authority": "Rajya Shiksha Kendra (RSK) MP",
        "official_url": "https://www.rskmp.in",
        "alias": "MP",
        "hindi_name": "मध्य प्रदेश",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय"]
    },
    "Haryana": {
        "authority": "BSEH / SCERT Haryana",
        "official_url": "https://bseh.org.in",
        "alias": "Haryana",
        "hindi_name": "हरियाणा",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय"]
    },
    "Delhi": {
        "authority": "Directorate of Education Delhi",
        "official_url": "https://edudel.nic.in",
        "alias": "Delhi",
        "hindi_name": "दिल्ली",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय"]
    },
    "Jharkhand": {
        "authority": "JAC Jharkhand",
        "official_url": "https://jac.jharkhand.gov.in",
        "alias": "Jharkhand",
        "hindi_name": "झारखंड",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय"]
    },
    "Chhattisgarh": {
        "authority": "SCERT Chhattisgarh",
        "official_url": "https://scert.cg.gov.in",
        "alias": "CG",
        "hindi_name": "छत्तीसगढ़",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय"]
    },
    "Himachal Pradesh": {
        "authority": "SCERT HP",
        "official_url": "https://himachalservices.nic.in/scert",
        "alias": "HP",
        "hindi_name": "हिमाचल प्रदेश",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय"]
    },
    "Uttarakhand": {
        "authority": "SCERT Uttarakhand",
        "official_url": "https://scert.uk.gov.in",
        "alias": "UK",
        "hindi_name": "उत्तराखंड",
        "keywords": ["NMMS", "NMMSS", "National Means", "राष्ट्रीय आय"]
    }
}
