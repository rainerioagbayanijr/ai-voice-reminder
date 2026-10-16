from string import Formatter

from app.core.config import Settings
from app.models import VoiceRequest
from app.services.dates import display_english_date, spoken_english_date

ALLOWED = {"first_name", "bank_name", "agent_name", "due_date"}


class Templates:
    def __init__(self, settings: Settings):
        self.language = settings.language
        self.templates = {}
        for name in ("voice", "subject", "email"):
            path = settings.template_dir / settings.language / f"{name}.txt"
            template = path.read_text(encoding="utf-8").strip()
            if not template or len(template) > 4000:
                raise ValueError("Templates must contain between 1 and 4000 characters")
            if name == "subject" and any(c in template for c in "\r\n"):
                raise ValueError("Subject template must be a single line")
            for _, field, spec, conversion in Formatter().parse(template):
                if field is not None and (field not in ALLOWED or spec or conversion):
                    raise ValueError("Unsupported template placeholder")
            self.templates[name] = template

    def render(self, name: str, customer: VoiceRequest) -> str:
        context = customer.model_dump(include=ALLOWED - {"due_date"})
        due = customer.due_date
        context["due_date"] = (
            spoken_english_date(due)
            if name == "voice" and self.language == "fil"
            else display_english_date(due)
        )
        result = self.templates[name].format_map(context)
        if len(result) > 5000 or (name == "subject" and any(c in result for c in "\r\n")):
            raise ValueError("Invalid rendered template")
        return result
