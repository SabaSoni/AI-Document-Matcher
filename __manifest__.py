# -*- coding: utf-8 -*-
{
    "name": "AI Document Search (Georgian)",
    "summary": "Upload Word/PDF, extract Georgian text, optional AI enrichment, "
               "and make every word searchable from the search bar.",
    "description": """
AI Document Search (Georgian)
=============================

Makes the *contents* of uploaded Georgian Word (.docx) and PDF files searchable.

* Upload a file on an AI Document record; the text is extracted automatically
  (pypdf for PDF, python-docx for Word paragraphs and tables).
* The text is stored in a trigram-indexed field, so typing any word in the
  search bar finds every document that contains it - not only by title.
* Optional: with an Anthropic API key set in System Parameters, each document
  also gets a short Georgian summary and a keyword list (also searchable).
* Draft / Processed / Error status with a processing log and chatter tracking.

Requires the Python packages ``pypdf`` and ``python-docx``.
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
