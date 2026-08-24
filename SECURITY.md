# Security policy

## Supported version

Only the latest Eaststone-approved release is supported. Production installations should use an immutable reviewed commit and follow the controlled update procedure.

## Reporting a vulnerability

Do not disclose a suspected vulnerability, credential, document path, employee record or production evidence in a public GitHub issue. Report it through Eaststone's authorised information-security/quality incident channel with the affected version, reproducible steps and impact. Preserve relevant audit and server logs.

## Dependency review

CI runs deterministic builds and Dependabot is configured monthly. Release qualification must also run `pip-audit -r api/requirements.txt` and `npm audit --omit=dev`, review findings in context and record the result before approval.
