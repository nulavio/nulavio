"""Nulavio Vault: encrypted-profile keys and their unlock methods (ADR 0005, ADR 0006).

`core` holds the profile DEK and its envelopes, `providers` the OS keyring,
`phone` the nv1 protocol (desktop side), `coordinator` the unlock state
machine. Needs the system libsodium (`sodium.available()`).
"""
