# -*- coding: utf-8 -*-
import base64
import io
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional third-party libraries. We import them lazily / defensively so the
# module still LOADS even if a library is missing; extraction then fails with a
# clear message instead of breaking the whole server.
# ---------------------------------------------------------------------------
try:
    from pypdf import PdfReader  # modern package
except Exception:  # pragma: no cover
    try:
        from PyPDF2 import PdfReader  # legacy fallback
    except Exception:
        PdfReader = None

try:
    import docx  # python-docx  (pip install python-docx)
except Exception:  # pragma: no cover
    docx = None

# 'requests' ships with Odoo, but we still guard it.
try:
    import requests
except Exception:  # pragma: no cover
    requests = None


class AiDocument(models.Model):
    _name = "ai.document"
    _description = "AI Searchable Document"
    _inherit = ["mail.thread"]
    _order = "create_date desc"
    # _rec_name defaults to 'name'

    name = fields.Char(
        string="Title", required=True, index=True, tracking=True,
        help="Document title. If left as the default it is replaced by the filename.",
    )
    file = fields.Binary(string="File", attachment=True, required=True)
    filename = fields.Char(string="Filename")

    file_type = fields.Selection(
        selection=[
            ("pdf", "PDF"),
            ("docx", "Word (DOCX)"),
            ("other", "Other"),
        ],
        string="File Type",
        compute="_compute_file_type",
        store=True,
    )

    # The searchable field. 'trigram' index makes 'ilike' (contains) searches
    # fast even on large text — this is what powers the search bar.
    extracted_text = fields.Text(
        string="Extracted Text",
        index="trigram",
        help="Full text pulled out of the uploaded file. Searchable from the search bar.",
    )

    # --- Optional AI output ------------------------------------------------
    summary = fields.Text(string="AI Summary", readonly=True)
    keywords = fields.Char(
        string="AI Keywords", readonly=True, index="trigram",
        help="Comma-separated keywords produced by the AI pass. Also searchable.",
    )

    language = fields.Char(string="Language", default="ka")
    char_count = fields.Integer(
        string="Characters", compute="_compute_char_count", store=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("processed", "Processed"),
            ("error", "Error"),
        ],
        string="Status", default="draft", tracking=True,
    )
    processing_log = fields.Text(string="Processing Log", readonly=True)
    active = fields.Boolean(default=True)

    # ------------------------------------------------------------------ #
    #  Computes
    # ------------------------------------------------------------------ #
    @api.depends("filename")
    def _compute_file_type(self):
        for rec in self:
            name = (rec.filename or "").lower()
            if name.endswith(".pdf"):
                rec.file_type = "pdf"
            elif name.endswith(".docx"):
                rec.file_type = "docx"
            elif name.endswith(".doc"):
                # legacy binary .doc is not supported by python-docx
                rec.file_type = "other"
            else:
                rec.file_type = "other"

    @api.depends("extracted_text")
    def _compute_char_count(self):
        for rec in self:
            rec.char_count = len(rec.extracted_text or "")

    # ------------------------------------------------------------------ #
    #  Create / write hooks — auto-process on upload
    # ------------------------------------------------------------------ #
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.file:
                # Never let an extraction problem block record creation.
                rec._process(raise_on_error=False)
        return records

    def write(self, vals):
        res = super().write(vals)
        # If a NEW file was uploaded onto an existing record, re-extract.
        if "file" in vals and vals.get("file"):
            for rec in self:
                rec._process(raise_on_error=False)
        return res

    # ------------------------------------------------------------------ #
    #  Buttons
    # ------------------------------------------------------------------ #
    def action_process(self):
        """Manual (re)processing button — surfaces errors to the user."""
        for rec in self:
            rec._process(raise_on_error=True)
        return True

    # ------------------------------------------------------------------ #
    #  Core pipeline
    # ------------------------------------------------------------------ #
    def _process(self, raise_on_error=True):
        self.ensure_one()
        log_lines = []
        try:
            if not self.file:
                raise UserError(_("No file uploaded."))

            data = base64.b64decode(self.file)

            # Default the title to the filename if user left it empty-ish.
            if self.filename and (not self.name or self.name in ("New", _("New"))):
                self.name = self.filename

            ftype = self.file_type
            log_lines.append(_("Detected file type: %s") % (ftype or "unknown"))

            if ftype == "pdf":
                text = self._extract_text_from_pdf(data)
            elif ftype == "docx":
                text = self._extract_text_from_docx(data)
            else:
                raise UserError(_(
                    "Unsupported file type. Please upload a .pdf or .docx file. "
                    "(Old .doc files must be re-saved as .docx.)"
                ))

            text = (text or "").strip()
            self.extracted_text = text
            log_lines.append(_("Extracted %d characters.") % len(text))

            if not text:
                log_lines.append(_(
                    "Warning: no text found. The PDF may be a scanned image — "
                    "OCR would be required (see documentation)."
                ))

            # Optional AI enrichment (summary + keywords).
            if text and self._ai_enabled():
                try:
                    self._run_ai_enrichment(text)
                    log_lines.append(_("AI enrichment: done."))
                except Exception as ai_err:  # non-fatal
                    log_lines.append(_("AI enrichment skipped: %s") % ai_err)

            self.state = "processed"
            self.processing_log = "\n".join(log_lines)

        except Exception as err:
            _logger.exception("ai.document processing failed for id=%s", self.id)
            self.state = "error"
            log_lines.append(_("ERROR: %s") % err)
            self.processing_log = "\n".join(log_lines)
            if raise_on_error:
                raise
        return True

    # ------------------------------------------------------------------ #
    #  Extractors
    # ------------------------------------------------------------------ #
    def _extract_text_from_pdf(self, data):
        if PdfReader is None:
            raise UserError(_(
                "The 'pypdf' library is not installed on the server.\n"
                "Install it with:  pip install pypdf"
            ))
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                # A single unreadable page shouldn't kill the whole doc.
                parts.append("")
        return "\n".join(parts)

    def _extract_text_from_docx(self, data):
        if docx is None:
            raise UserError(_(
                "The 'python-docx' library is not installed on the server.\n"
                "Install it with:  pip install python-docx"
            ))
        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        # Also pull text out of tables — often where structured data lives.
        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text:
                        parts.append(cell.text)
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    #  Optional AI enrichment (Anthropic / Claude)
    # ------------------------------------------------------------------ #
    def _ai_enabled(self):
        key = self.env["ir.config_parameter"].sudo().get_param(
            "ai_document.anthropic_api_key"
        )
        return bool(key) and requests is not None

    def _run_ai_enrichment(self, text):
        """Ask an LLM for a short Georgian summary + keywords.

        Controlled by system parameters (Settings > Technical > Parameters):
          ai_document.anthropic_api_key   -> your API key
          ai_document.anthropic_model     -> model name (optional)
        Requires the Odoo server to have outbound internet access
        (works on Odoo.sh / on-premise; blocked on Odoo Online SaaS).
        """
        ICP = self.env["ir.config_parameter"].sudo()
        api_key = ICP.get_param("ai_document.anthropic_api_key")
        model = ICP.get_param("ai_document.anthropic_model") or "claude-haiku-4-5-20251001"

        # Keep the prompt payload bounded.
        snippet = text[:12000]
        prompt = (
            "შენ ხარ დამხმარე, რომელიც ამუშავებს ქართულ დოკუმენტებს. "
            "ქვემოთ მოცემული ტექსტისთვის დააბრუნე მხოლოდ JSON ობიექტი, "
            'ფორმატით: {"summary": "...", "keywords": ["...", "..."]}. '
            "summary — 2-3 წინადადება ქართულად. keywords — 5-12 საკვანძო სიტყვა ქართულად.\n\n"
            "ტექსტი:\n" + snippet
        )

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            data=json.dumps({
                "model": model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }),
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()

        # Join all text blocks from the response.
        raw = "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if block.get("type") == "text"
        ).strip()

        # Be tolerant of code fences the model might add.
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)

        self.summary = parsed.get("summary") or ""
        kws = parsed.get("keywords") or []
        if isinstance(kws, list):
            self.keywords = ", ".join(str(k) for k in kws)
        else:
            self.keywords = str(kws)

    # ------------------------------------------------------------------ #
    #  Search: make the search bar look inside the extracted text too.
    # ------------------------------------------------------------------ #
    @api.model
    def _name_search(self, name, domain=None, operator="ilike", limit=None, order=None):
        """When someone types in the search bar / a many2one, also match the
        text pulled out of the document and the AI keywords — not just the title."""
        domain = list(domain or [])
        if name and operator in ("ilike", "like", "=", "=ilike", "=like"):
            extra = [
                "|", "|",
                ("name", operator, name),
                ("extracted_text", operator, name),
                ("keywords", operator, name),
            ]
            domain = extra + domain
            return self._search(domain, limit=limit, order=order)
        return super()._name_search(
            name, domain=domain, operator=operator, limit=limit, order=order
        )
