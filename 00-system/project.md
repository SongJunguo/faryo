# Faryo

## Purpose
Multi-owner AI workbench and project control runtime.

## Control
- Owner: GCP
- Project root: `/home/summer/brain/tools/faryo`
- Current state file: `00-system/workbench.json`

## Current Goal
Generalize project workbench ownership and absorb the old project-governance skill into Faryo's import, owner routing, and verified writeback flow.

## Worker Contract
- Keep `00-system/workbench.json` current during project work.
- Update decision, action, and watch items before closing a managed work session.
- Do not treat this file as the live task board; it is the stable project definition.

