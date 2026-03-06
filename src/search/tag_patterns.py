"""Tag pattern definitions for environment detection."""

import re

# Git remote patterns — hosting platforms only
# Organization-specific patterns are learned dynamically via tag relevance scoring.
GIT_REMOTE_PATTERNS = [
    (re.compile(r"github\.com"), "github"),
    (re.compile(r"bitbucket\.org"), "bitbucket"),
    (re.compile(r"gitlab\.com"), "gitlab"),
]

# File marker patterns
FILE_MARKERS = {
    "tsconfig.json": ["typescript"],
    "package.json": [],
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
    "koa": ["nodejs", "backend"],
    "hapi": ["nodejs", "backend"],
    "nest": ["nestjs", "nodejs", "backend"],
    "@nestjs/core": ["nestjs", "nodejs", "backend"],
    "node-fetch": ["nodejs"],
    "nodemon": ["nodejs"],
    "pm2": ["nodejs"],
    "mongoose": ["nodejs", "mongodb"],
    "sequelize": ["nodejs", "sql"],
    "prisma": ["nodejs", "sql"],
    "@prisma/client": ["nodejs", "sql"],
    "typescript": ["typescript"],
    "jest": ["jest", "testing"],
    "vitest": ["vitest", "testing"],
    "playwright": ["playwright", "testing"],
    "cypress": ["cypress", "testing"],
}

# Gemfile dependency patterns
GEMFILE_DEPENDENCY_TAGS = {
    "rails": ["rails", "backend"],
    "rspec": ["rspec", "testing"],
    "rubocop": ["ruby"],
}
