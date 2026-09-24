# -*- coding: utf-8 -*-
{
    "name": "AI Document Search (Georgian)",
    "summary": "Upload Word/PDF, extract Georgian text, optional AI enrichment, "
               "and make every word searchable from the search bar.",
    "description": """
Upload a Georgian Word (.docx) or PDF file. Extracted text is stored and
searchable from the search bar. Optional AI summary/keywords via Anthropic.
    """,
    "author": "FMG Soft",
    "website": "https://fmgsoft.ge",
    "category": "Productivity/Documents",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["base", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/config_parameters.xml",
        "views/ai_document_views.xml",
    ],
    "external_dependencies": {
        "python": ["pypdf", "docx"],
    },
    "installable": True,
    "application": True,
}
