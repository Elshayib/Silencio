# Public GitHub distribution with local audio processing

The owner chose public source and downloads on GitHub so installed users can
update without accounts or embedded credentials. This supersedes ADR-0003's
blanket prohibition on networking only for the isolated update client:
it fetches release metadata and installers, while all audio processing stays
offline and microphone capture remains prohibited. Installation requires user
consent, a verified download and graceful audio restoration before replacement.
