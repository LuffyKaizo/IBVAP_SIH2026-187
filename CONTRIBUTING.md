# Contributing to IBVAP

## Workflow

1. Pull latest `main`
2. Create a feature branch
3. Implement focused change
4. Run tests and build
5. Commit with descriptive message
6. Push and open a Pull Request
7. Review and merge

## Branch Naming

```
feature/<short-description>
fix/<short-description>
docs/<short-description>
refactor/<short-description>
experiment/<short-description>
```

Examples:
- `feature/anpr-confidence-filter`
- `fix/websocket-reconnect`
- `docs/api-endpoints`

## Commit Messages

Use conventional prefixes:

| Prefix | Usage |
|--------|-------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `test:` | Adding or updating tests |
| `refactor:` | Code restructuring without behavior change |
| `chore:` | Build, CI, dependency updates |

Examples:
- `feat: add fence proximity alert escalation`
- `fix: resolve track ID reset on camera restart`
- `docs: update TEAM_SETUP with migration steps`

## Requirements

### Before Submitting a PR

- [ ] Tests pass (`python -m pytest` for backend, `npx tsc --noEmit` for frontend)
- [ ] Build succeeds (`npm run build`)
- [ ] No hardcoded secrets or passwords
- [ ] No `.env` files committed
- [ ] Documentation updated if behavior changes
- [ ] New features have corresponding tests

### Code Style

- **Python:** Follow existing patterns in `backend/ai/`. Use type hints. Keep functions focused.
- **TypeScript:** Follow existing patterns in `frontend/src/`. Use proper typing. No `any`.
- **Tests:** Mock external dependencies (database, network). Use descriptive test names.

## Security Rules

**Never commit:**
- `.env` files
- Passwords, tokens, API keys
- Private keys (`*.key`, `*.pem`)
- Database credentials
- Real surveillance footage (unless explicitly approved)
- Datasets (unless explicitly approved)
- Runtime evidence files

**Always:**
- Use environment variables for secrets
- Hash passwords with bcrypt
- Verify JWT tokens on protected endpoints
- Use parameterized queries (SQLAlchemy handles this)

## Pull Request Process

1. Fill in the PR template completely
2. Describe what changed and why
3. Note any breaking changes or database migrations
4. Add screenshots for UI changes
5. Reference related issues if applicable
6. Request review from CODEOWNERS

## CODEOWNERS

See `.github/CODEOWNERS` for code ownership. Reviewers are automatically requested based on changed files.

## Questions?

Open an issue or reach out to the team.
