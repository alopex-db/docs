#!/bin/bash
#
# Pre-commit security check script
#
# Install as git hook:
#   cp scripts/pre-commit-check.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#
# Or run manually:
#   ./scripts/pre-commit-check.sh
#

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

echo "Running pre-commit security check..."
echo

ERRORS=0
WARNINGS=0

# Get staged files
if git rev-parse --verify HEAD >/dev/null 2>&1; then
    STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM)
else
    STAGED_FILES=$(git diff --cached --name-only)
fi

if [ -z "$STAGED_FILES" ]; then
    echo -e "${GREEN}No staged files to check${NC}"
    exit 0
fi

# Check for sensitive file patterns
echo "Checking for sensitive files..."
SENSITIVE_PATTERNS=(".env" ".env.*" "*.pem" "*.key" "*.p12" "id_rsa" "id_ed25519" "credentials" "secrets")

for file in $STAGED_FILES; do
    filename=$(basename "$file")
    for pattern in "${SENSITIVE_PATTERNS[@]}"; do
        if [[ "$filename" == $pattern ]]; then
            echo -e "${RED}ERROR: Sensitive file staged: $file${NC}"
            ((ERRORS++))
        fi
    done
done

# Check file contents
echo "Checking file contents..."

for file in $STAGED_FILES; do
    # Skip binary files
    if file "$file" | grep -q "binary"; then
        continue
    fi

    # Skip if file doesn't exist (deleted)
    if [ ! -f "$file" ]; then
        continue
    fi

    # Check for local paths
    if grep -nE '/home/[^/]+/|/Users/[^/]+/|C:\\Users\\' "$file" 2>/dev/null; then
        echo -e "${YELLOW}WARNING: Local path in $file${NC}"
        ((WARNINGS++))
    fi

    # Check for private IPs
    if grep -nE '192\.168\.[0-9]+\.[0-9]+|10\.[0-9]+\.[0-9]+\.[0-9]+' "$file" 2>/dev/null; then
        echo -e "${YELLOW}WARNING: Private IP in $file${NC}"
        ((WARNINGS++))
    fi

    # Check for API keys
    if grep -nE 'sk-[a-zA-Z0-9]{32,}|ghp_[a-zA-Z0-9]{36}|ghs_[a-zA-Z0-9]{36}|AKIA[A-Z0-9]{16}' "$file" 2>/dev/null; then
        echo -e "${RED}ERROR: API key detected in $file${NC}"
        ((ERRORS++))
    fi

    # Check for hardcoded passwords
    if grep -niE 'password\s*[=:]\s*["\047][^"\047]+["\047]' "$file" 2>/dev/null | grep -v 'example\|placeholder\|your_'; then
        echo -e "${RED}ERROR: Hardcoded password in $file${NC}"
        ((ERRORS++))
    fi
done

echo
echo "========================================="
echo "Security Check Summary"
echo "========================================="
echo -e "Errors:   ${RED}$ERRORS${NC}"
echo -e "Warnings: ${YELLOW}$WARNINGS${NC}"

if [ $ERRORS -gt 0 ]; then
    echo
    echo -e "${RED}Commit blocked due to security errors.${NC}"
    echo "Please fix the issues above before committing."
    echo
    echo "To bypass this check (not recommended):"
    echo "  git commit --no-verify"
    exit 1
fi

if [ $WARNINGS -gt 0 ]; then
    echo
    echo -e "${YELLOW}Warnings detected. Please review before pushing.${NC}"
fi

echo
echo -e "${GREEN}Security check passed.${NC}"
exit 0
