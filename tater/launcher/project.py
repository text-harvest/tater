"""The project file: what the admin writes to describe a project (YAML).

``load_project(path)`` parses and validates it, resolving paths against the
project file's folder; ``check_project(project)`` also loads the schema and the
documents, as each annotator's tater process will.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class ProjectError(Exception):
    """The project file, or a file it names, is unusable. The message says why."""


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, name: str) -> str:
        if not NAME_PATTERN.match(name):
            raise ValueError(
                "must be lower-case letters, digits, '-' or '_', starting with a letter or digit "
                "(it names the annotator's results folder)"
            )
        return name

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, email: Optional[str]) -> Optional[str]:
        return email.strip().lower() if email else None


class Annotator(Person):
    documents: Optional[Path] = None


class ProjectFile(BaseModel):
    """The project file as written; paths are still relative to it."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str = "tater project"
    schema_file: Optional[Path] = Field(None, alias="schema")
    config: Optional[Path] = None
    documents: Path
    results: Path
    identity: Literal["links", "header"] = "links"
    header: Optional[str] = None
    public_url: Optional[str] = None
    idle_minutes: float = Field(30, ge=0)
    annotators: list[Annotator] = Field(min_length=1)
    admins: list[Person] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "ProjectFile":
        if (self.schema_file is None) == (self.config is None):
            raise ValueError("give exactly one of 'schema' (a JSON schema) or 'config' (a Python config)")
        names = [a.name for a in self.annotators]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"annotator names must be unique: {', '.join(dupes)}")
        admin_names = [a.name for a in self.admins]
        dupes = sorted({n for n in admin_names if admin_names.count(n) > 1})
        if dupes:
            raise ValueError(f"admin names must be unique: {', '.join(dupes)}")
        by_name = {a.name: a for a in self.annotators}
        for admin in self.admins:
            # The same person may be both, but then it must be the same person.
            other = by_name.get(admin.name)
            if other is not None and other.email != admin.email:
                raise ValueError(f"'{admin.name}' is both an annotator and an admin with different emails")
        if self.identity == "header":
            if not self.header:
                raise ValueError("identity: header needs 'header', the request header carrying the email")
            missing = [p.name for p in [*self.annotators, *self.admins] if not p.email]
            if missing:
                raise ValueError(f"identity: header needs an email for: {', '.join(missing)}")
            emails = [p.email for p in self.annotators]
            dupes = sorted({e for e in emails if emails.count(e) > 1})
            if dupes:
                raise ValueError(f"annotator emails must be unique: {', '.join(dupes)}")
        return self


@dataclass
class Project:
    """A loaded project: the file's settings with every path made absolute."""

    file: ProjectFile
    path: Path

    @property
    def project_dir(self) -> Path:
        return self.path.parent

    @property
    def state_dir(self) -> Path:
        """Launcher state (signing key, links, status): beside the project file, not
        in results, so the results folder can be handed over as it is."""
        return self.project_dir / f"{self.path.stem}.launcher"

    @property
    def schema_path(self) -> Optional[Path]:
        return self._abs(self.file.schema_file)

    @property
    def config_path(self) -> Optional[Path]:
        return self._abs(self.file.config)

    @property
    def results_dir(self) -> Path:
        return self._abs(self.file.results)

    @property
    def annotators(self) -> list[Annotator]:
        return self.file.annotators

    @property
    def admins(self) -> list[Person]:
        return self.file.admins

    def annotator(self, name: str) -> Optional[Annotator]:
        return next((a for a in self.file.annotators if a.name == name), None)

    def documents_path(self, name: str) -> Path:
        annotator = self.annotator(name)
        own = annotator.documents if annotator else None
        return self._abs(own or self.file.documents)

    def annotation_path(self, name: str) -> Path:
        return self.results_dir / name / "annotations.json"

    def log_path(self, name: str) -> Path:
        return self.results_dir / name / "tater.log"

    def _abs(self, p: Optional[Path]) -> Optional[Path]:
        if p is None:
            return None
        p = Path(p).expanduser()
        return p if p.is_absolute() else (self.project_dir / p).resolve()


def _describe(error: ValidationError) -> str:
    lines = []
    for err in error.errors():
        where = ".".join(str(p) for p in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        if err["type"] == "extra_forbidden":
            msg = "not a project file setting (misspelt?)"
        lines.append(f"  {where}: {msg}" if where else f"  {msg}")
    return "\n".join(lines)


def load_project(path: str | Path) -> Project:
    """Parse and validate a project file; check the files it names exist."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ProjectError(f"project file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise ProjectError(f"{path.name} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ProjectError(f"{path.name} must be a YAML mapping of settings")
    try:
        project = Project(file=ProjectFile.model_validate(data), path=path)
    except ValidationError as e:
        raise ProjectError(f"{path.name} has problems:\n{_describe(e)}") from e

    missing = []
    for label, p in [("schema", project.schema_path), ("config", project.config_path)]:
        if p is not None and not p.is_file():
            missing.append(f"  {label}: {p}")
    for p in sorted({project.documents_path(a.name) for a in project.annotators}):
        if not p.is_file():
            missing.append(f"  documents: {p}")
    if missing:
        raise ProjectError(f"{path.name} names files that don't exist:\n" + "\n".join(missing))
    if project.file.public_url:
        project.file.public_url = project.file.public_url.rstrip("/")
    return project


def check_project(project: Project) -> list[str]:
    """Load the schema (or config) and every documents file as tater would.

    Returns report lines; raises ProjectError on the first thing that won't load.
    """
    report = []
    try:
        if project.config_path:
            from tater.ui.config_loader import load_config_module
            config = load_config_module(str(project.config_path))
            source = f"config {project.config_path.name}"
        else:
            from tater.loaders import load_schema
            config = load_schema(str(project.schema_path))
            source = f"schema {project.schema_path.name}"
    except Exception as e:
        raise ProjectError(f"the schema doesn't load: {e}") from e
    model = config.get("schema_model")
    if model is None:
        raise ProjectError(f"{source} defines no schema (a config needs a 'Schema' model)")
    required = [n for n, f in model.model_fields.items() if f.is_required()]
    if required:
        raise ProjectError(f"every schema field needs a default; these have none: {', '.join(required)}")
    report.append(f"{source}: {len(model.model_fields)} fields")

    from tater.loaders import load_documents
    counts: dict[Path, int] = {}
    for annotator in project.annotators:
        docs_path = project.documents_path(annotator.name)
        if docs_path not in counts:
            try:
                counts[docs_path] = len(load_documents(docs_path))
            except Exception as e:
                raise ProjectError(f"documents {docs_path} don't load: {e}") from e
        report.append(f"{annotator.name}: {counts[docs_path]} documents from {docs_path.name}")
    report.append(f"results: {project.results_dir}")
    return report
