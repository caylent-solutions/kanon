#!/usr/bin/env bash

# Project-specific setup script
# This script runs after the main devcontainer setup is complete
# Add your project-specific initialization commands here
#
# Examples:
# - make configure
# - npm install
# - pip install -r requirements.txt
# - docker-compose up -d
# - Initialize databases
# - Download project dependencies
# - Run project-specific configuration

set -euo pipefail


log_info "Running project-specific setup..."

# Add your project setup commands below this line
# Example:
# if [ -f "Makefile" ]; then
#   log_info "Running make configure..."
#   make configure
# fi
log_info "Add project specific setup commands here!"

log_info "Adding grm alias (git reset main)..."
GRM_ALIAS='alias grm="git fetch --prune origin && git checkout main && git reset --hard origin/main && git clean -fdx"'
echo "$GRM_ALIAS" >> "${HOME}/.bashrc"
echo "$GRM_ALIAS" >> "${HOME}/.zshrc"

log_info "Project-specific setup complete"
