# Profile stats workflow setup

The scheduled workflow fetches GitHub data, renders the palette-matched SVG cards, refreshes the recent public projects table, and commits changed output to the default branch once per day. It can also be run from **Actions → Refresh profile stats → Run workflow**.

## Configure the API token

Add two Actions repository secrets:

1. Create a short-lived fine-grained personal access token for `AatirNadim`. Select the `AatirNadim` resource owner, grant access to all of your owned repositories, and give **Metadata** read-only permission. Save it as `GH_STATS_TOKEN`. This reads repository counts and language totals without granting code or write access.
2. Create a short-lived classic personal access token with only the `read:user` scope. Save it as `GH_CONTRIBUTIONS_TOKEN`. GitHub requires this user scope for private contribution counts.
3. In this repository, open **Settings → Secrets and variables → Actions → New repository secret** and add each token under its name above.

The generator only makes read requests with these tokens and never uses them to commit. The workflow commits with its separate `GITHUB_TOKEN`, which is limited to writing this profile repository. Do not print or pass a secret as a command-line argument.

Choose token expiration dates you can maintain, then renew both tokens and update the repository secrets before they expire. Otherwise the scheduled sync will fail until the secrets are replaced.

GitHub's contribution calendar includes private contribution counts only when private contribution display is enabled in the account's profile settings. Repository counts and language totals include owned public and private repositories visible to `GH_STATS_TOKEN`; collaborator and organization repositories are excluded to avoid publishing aggregate data about third-party code.

## Public output and privacy

The generated overview publishes aggregate repository counts, private repository count, star total, and follower count. The language chart merges language byte counts across owned non-fork repositories; it does not publish a per-repository breakdown. Contribution activity is aggregate. Recent project links are retrieved from the public repositories endpoint and filtered to public, non-fork, non-archived repositories; the profile repository itself is excluded.

Private repository names, URLs, descriptions, per-repository language totals, and update times are never written into the README, SVGs, or committed generated data. Stats derived from private repositories are still public once rendered, so the aggregate counts and language distribution are intentional public disclosures.

The workflow runs daily at 05:37 UTC, away from the top of the hour when scheduled jobs are more likely to be delayed. GitHub can still delay scheduled runs during busy periods; manual dispatch is available for an immediate refresh.
