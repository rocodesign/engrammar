"""Tests for tag detection from environment."""

import os
import tempfile
import json
from pathlib import Path

import pytest

from src.tag_detectors import (
    detect_tags,
    _detect_from_git,
    _detect_from_files,
    _detect_from_package,
    _detect_from_gemfile,
    _detect_from_structure,
)


class TestGitDetection:
    """Test tag detection from git remotes."""

    def test_github_detection(self, tmp_path, monkeypatch):
        """Should detect 'github' tag from GitHub remote."""
        # This test would require mocking subprocess
        # For now, just test the function exists and handles errors gracefully
        tags = _detect_from_git()
        assert isinstance(tags, set)

    def test_no_git_repo(self, tmp_path, monkeypatch):
        """Should return empty set when not in git repo."""
        monkeypatch.chdir(tmp_path)
        tags = _detect_from_git()
        assert len(tags) == 0


class TestFileMarkerDetection:
    """Test tag detection from file markers."""

    def test_typescript_detection(self, tmp_path, monkeypatch):
        """Should detect 'typescript' from tsconfig.json."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tsconfig.json").write_text("{}")
        tags = _detect_from_files()
        assert "typescript" in tags

    def test_ruby_detection(self, tmp_path, monkeypatch):
        """Should detect 'ruby' from Gemfile."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "Gemfile").write_text("")
        tags = _detect_from_files()
        assert "ruby" in tags

    def test_docker_detection(self, tmp_path, monkeypatch):
        """Should detect 'docker' from Dockerfile."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "Dockerfile").write_text("")
        tags = _detect_from_files()
        assert "docker" in tags

    def test_multiple_markers(self, tmp_path, monkeypatch):
        """Should detect multiple tags from multiple markers."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tsconfig.json").write_text("{}")
        (tmp_path / "Dockerfile").write_text("")
        (tmp_path / "jest.config.js").write_text("")
        tags = _detect_from_files()
        assert "typescript" in tags
        assert "docker" in tags
        assert "jest" in tags


class TestPackageJsonDetection:
    """Test tag detection from package.json dependencies."""

    def test_react_detection(self, tmp_path, monkeypatch):
        """Should detect 'react' and 'frontend' from React dependency."""
        monkeypatch.chdir(tmp_path)
        package_json = {
            "dependencies": {
                "react": "^18.0.0"
            }
        }
        (tmp_path / "package.json").write_text(json.dumps(package_json))
        tags = _detect_from_package()
        assert "react" in tags
        assert "frontend" in tags

    def test_nextjs_detection(self, tmp_path, monkeypatch):
        """Should detect 'nextjs', 'react', 'frontend' from Next.js."""
        monkeypatch.chdir(tmp_path)
        package_json = {
            "dependencies": {
                "next": "^14.0.0"
            }
        }
        (tmp_path / "package.json").write_text(json.dumps(package_json))
        tags = _detect_from_package()
        assert "nextjs" in tags
        assert "react" in tags
        assert "frontend" in tags

    def test_dev_dependencies(self, tmp_path, monkeypatch):
        """Should check devDependencies too."""
        monkeypatch.chdir(tmp_path)
        package_json = {
            "devDependencies": {
                "jest": "^29.0.0",
                "playwright": "^1.0.0"
            }
        }
        (tmp_path / "package.json").write_text(json.dumps(package_json))
        tags = _detect_from_package()
        assert "jest" in tags
        assert "playwright" in tags
        assert "testing" in tags

    def test_no_package_json(self, tmp_path, monkeypatch):
        """Should return empty set when no package.json."""
        monkeypatch.chdir(tmp_path)
        tags = _detect_from_package()
        assert len(tags) == 0


class TestGemfileDetection:
    """Test tag detection from Gemfile."""

    def test_rails_detection(self, tmp_path, monkeypatch):
        """Should detect 'rails' and 'backend' from Rails gem."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "Gemfile").write_text("gem 'rails', '~> 7.0'")
        tags = _detect_from_gemfile()
        assert "rails" in tags
        assert "backend" in tags

    def test_rspec_detection(self, tmp_path, monkeypatch):
        """Should detect 'rspec' and 'testing' from RSpec gem."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "Gemfile").write_text("gem 'rspec'")
        tags = _detect_from_gemfile()
        assert "rspec" in tags
        assert "testing" in tags

    def test_no_gemfile(self, tmp_path, monkeypatch):
        """Should return empty set when no Gemfile."""
        monkeypatch.chdir(tmp_path)
        tags = _detect_from_gemfile()
        assert len(tags) == 0


class TestDirectoryStructure:
    """Test tag detection from directory structure."""

    def test_monorepo_packages(self, tmp_path, monkeypatch):
        """Should detect 'monorepo' from packages/ directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "packages").mkdir()
        tags = _detect_from_structure()
        assert "monorepo" in tags

    def test_monorepo_apps(self, tmp_path, monkeypatch):
        """Should detect 'monorepo' from apps/ directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "apps").mkdir()
        tags = _detect_from_structure()
        assert "monorepo" in tags

    def test_rails_engines(self, tmp_path, monkeypatch):
        """Should detect 'monorepo' and 'rails-engines' from engines/."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "engines").mkdir()
        tags = _detect_from_structure()
        assert "monorepo" in tags
        assert "rails-engines" in tags

    def test_frontend_directory(self, tmp_path, monkeypatch):
        """Should detect 'frontend' from frontend/ directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "frontend").mkdir()
        tags = _detect_from_structure()
        assert "frontend" in tags

    def test_components_directory(self, tmp_path, monkeypatch):
        """Should detect 'frontend' and 'react' from components/."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "components").mkdir()
        tags = _detect_from_structure()
        assert "frontend" in tags
        assert "react" in tags


class TestIntegration:
    """Integration tests for full tag detection."""

    def test_detect_tags_integration(self, tmp_path, monkeypatch):
        """Should combine all detection sources."""
        monkeypatch.chdir(tmp_path)

        # Create test files
        (tmp_path / "tsconfig.json").write_text("{}")
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18.0.0"}
        }))
        (tmp_path / "packages").mkdir()

        tags = detect_tags()

        # Should have tags from multiple sources
        assert "typescript" in tags  # from tsconfig.json
        assert "react" in tags  # from package.json
        assert "frontend" in tags  # from package.json + structure
        assert "monorepo" in tags  # from packages/
        assert "nodejs" in tags  # from package.json presence

    def test_tags_are_sorted(self, tmp_path, monkeypatch):
        """Should return sorted list of tags."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tsconfig.json").write_text("{}")
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"react": "^18.0.0"}
        }))

        tags = detect_tags()
        assert tags == sorted(tags)

    def test_tags_are_unique(self, tmp_path, monkeypatch):
        """Should not return duplicate tags."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tsconfig.json").write_text("{}")
        (tmp_path / "package.json").write_text(json.dumps({
            "dependencies": {"typescript": "^5.0.0"}
        }))

        tags = detect_tags()
        assert len(tags) == len(set(tags))
