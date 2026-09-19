"""Gmail integration.

The pipeline reads the organizers' files by default. This lets it read a real
mailbox over the Gmail API instead, seed that mailbox with the dataset, send
genuinely delivered mail, and write its triage back as labels.
"""
