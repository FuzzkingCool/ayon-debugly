# -*- coding: utf-8 -*-
"""Notion Issues DB field labels and helpers (must match studio Notion schema)."""

from __future__ import annotations

# Issue Type select — exact option names in Notion
ISSUE_TYPE_OPTIONS: tuple[str, ...] = (
    "Bug",
    "Feature",
    "Software & Accounts",
    "Tech Support & IT",
    "Task",
    "Systems & Infrastructure",
    "DevOps",
    "Documentation",
    "Research",
    "Planning",
    "Pipeline Support",
)

# Pipeline Release select — exact option names in Notion (lowercase).
# Use PIPELINE_* only for the Pipeline Release field (not the Project field).
PIPELINE_PRODUCTION = "production"
PIPELINE_STUDIO = "studio"
PIPELINE_ALL_RELEASES = "all releases"
# Alias: pipeline-only “all releases”; Project cross-project row is PROJECT_SELECT_STUDIO.
PIPELINE_SELECT_ALL_RELEASES = PIPELINE_ALL_RELEASES

PIPELINE_RELEASE_OPTIONS: tuple[str, ...] = (
    PIPELINE_PRODUCTION,
    PIPELINE_STUDIO,
    PIPELINE_ALL_RELEASES,
)

# Project select — cross-project row; must match Notion option name
PROJECT_SELECT_STUDIO = "Studio"


def default_pipeline_release_label() -> str:
    """Default Pipeline release shown in the report form (always production)."""
    return PIPELINE_PRODUCTION


def load_accessible_project_names() -> list[str]:
    """Projects the current logged-in user may access (AYON server-enforced list)."""
    import ayon_api

    projects: list = []
    try:
        if hasattr(ayon_api, "get_projects_list"):
            try:
                projects = ayon_api.get_projects_list(active=True, library=None) or []
            except TypeError:
                projects = ayon_api.get_projects_list() or []
        elif hasattr(ayon_api, "get_rest_projects_list"):
            try:
                projects = ayon_api.get_rest_projects_list(active=True, library=None) or []
            except TypeError:
                projects = ayon_api.get_rest_projects_list() or []
    except Exception:
        projects = []

    names: list[str] = []
    for p in projects:
        if isinstance(p, dict):
            n = p.get("name")
            if n:
                names.append(str(n))
        elif isinstance(p, str) and p:
            names.append(p)

    if not names:
        try:
            if hasattr(ayon_api, "get_project_names"):
                try:
                    raw = ayon_api.get_project_names(active=True, library=None)
                except TypeError:
                    raw = ayon_api.get_project_names()
                if raw:
                    names = [str(x) for x in raw if x]
        except Exception:
            pass

    return sorted(set(names), key=lambda x: x.lower())
