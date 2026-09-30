CONTAINER_COMPOSE ?= podman-compose
MICROMAMBA ?= micromamba
NEOVIM_VERSION ?= none

.DEFAULT_GOAL := help
.PHONY: help install update-dotfiles test test-cov container-build mamba-install \
	mamba-init mamba-env rust-install juliaup-install

help: ## Print this help message
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Run install.py (NEOVIM_VERSION=vX.Y.Z, EXTRACT_APPIMAGE=1 to customize)
ifeq ($(EXTRACT_APPIMAGE),1)
	./install.py --neovim-version $(NEOVIM_VERSION) --extract-appimage
else
	./install.py --neovim-version $(NEOVIM_VERSION)
endif

update-dotfiles: ## Sync dotfiles from $HOME into dotfiles/ (DOTFILES_ARGS="--dry-run" to preview)
	uv run sync_dotfiles.py $(DOTFILES_ARGS)

test: ## Run the test suite
	uv run --no-project --with pytest --with pyyaml pytest

test-cov: ## Run the test suite with a coverage report
	uv run --no-project --with pytest --with pytest-cov --with pyyaml \
		pytest --cov=sync_dotfiles --cov=install --cov=dotfiles --cov-report=term-missing

container-build: ## Build the dev container image (dev:latest)
	./dev-container/build.sh

mamba-install: ## Install micromamba
	curl -Ls https://raw.githubusercontent.com/cameronperot/shell-scripts/refs/heads/master/scripts/install_micromamba.sh | bash

mamba-init: ## Initialize micromamba for the current shell
	~/.micromamba/bin/micromamba shell init --root-prefix ~/.micromamba

mamba-env: ## Create the micromamba environment from environment.yml
	$(MICROMAMBA) create -f environment.yml

rust-install: ## Install Rust via rustup
	curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

juliaup-install: ## Install Julia via Juliaup
	curl -fsSL https://install.julialang.org | sh
