"""Tag pattern definitions for environment detection."""

import os
import re

# Path-based tag patterns
PATH_PATTERNS = [
    # Acme workspace
    (re.compile(r"/work/acme/"), "acme"),
    # Personal projects
    (re.compile(r"/work/app\.mo\.de"), "personal"),
    (re.compile(r"/work/sema-park-mobile"), "personal"),
    (re.compile(r"/work/autodivertis-v2"), "personal"),
    (re.compile(r"/work/via-dacica"), "personal"),
]

# Git remote patterns
GIT_REMOTE_PATTERNS = [
    # Hosting platforms
    (re.compile(r"github\.com"), "github"),
    (re.compile(r"bitbucket\.org"), "bitbucket"),
    (re.compile(r"gitlab\.com"), "gitlab"),
    # Organizations
    (re.compile(r"github\.com[:/]acme/"), "acme"),
    (re.compile(r"github\.com[:/]user/"), "personal"),
    (re.compile(r"bitbucket\.org[:/]codestoryteam/"), "personal"),
]

# File marker patterns
FILE_MARKERS = {
    "tsconfig.json": ["typescript"],
    "package.json": ["nodejs"],
    "Gemfile": ["ruby"],
    "requirements.txt": ["python"],
    "Cargo.toml": ["rust"],
    "go.mod": ["golang"],
    "pom.xml": ["java"],
    "build.gradle": ["java"],
    "Dockerfile": ["docker"],
    "docker-compose.yml": ["docker"],
    ".rubocop.yml": ["ruby"],
    "jest.config.js": ["jest"],
    "jest.config.ts": ["jest"],
    "playwright.config.ts": ["playwright"],
    "vite.config.ts": ["vite"],
    "next.config.js": ["nextjs"],
    "nuxt.config.ts": ["nuxtjs"],
}

# Directory structure patterns
DIR_STRUCTURE_PATTERNS = {
    "engines/": ["monorepo", "rails-engines"],
    "apps/": ["monorepo"],
    "packages/": ["monorepo"],
    "libs/": ["monorepo"],
    "frontend/": ["frontend"],
    "backend/": ["backend"],
    "src/": ["source"],
    "components/": ["frontend", "react"],
    "pages/": ["frontend"],
}

# package.json dependency patterns
PACKAGE_DEPENDENCY_TAGS = {
    "react": ["react", "frontend"],
    "next": ["nextjs", "react", "frontend"],
    "nuxt": ["nuxtjs", "vue", "frontend"],
    "vue": ["vue", "frontend"],
    "svelte": ["svelte", "frontend"],
    "angular": ["angular", "frontend"],
    "@angular/core": ["angular", "frontend"],
    "express": ["nodejs", "backend"],
    "fastify": ["nodejs", "backend"],
    "nest": ["nestjs", "nodejs", "backend"],
    "@nestjs/core": ["nestjs", "nodejs", "backend"],
    "typescript": ["typescript"],
    "jest": ["jest", "testing"],
    "vitest": ["vitest", "testing"],
    "playwright": ["playwright", "testing"],
    "cypress": ["cypress", "testing"],
    "@topkit/": ["acme", "topkit"],
    "@acme/davinci": ["acme", "davinci"],
    "@acme/picasso": ["acme", "picasso", "react", "frontend"],
}

# Gemfile dependency patterns
GEMFILE_DEPENDENCY_TAGS = {
    "rails": ["rails", "backend"],
    "rspec": ["rspec", "testing"],
    "rubocop": ["ruby"],
}
