# V1 backup custody plan

Status: **technical primary restore PASS; owner custody gate pending**

The encrypted bundle `v1-backup-restore-20260829T045502Z` remains the primary copy outside
production and Git. Its 16 encrypted payloads total 1,895,938,306 bytes. The manifest checksum is
`08ed9f6f55dd2aef32430124468b2ef7da26d50d21d916480e8ad3ae6e06e920`; the completed isolated
restore drill is already recorded in `v1-backup-restore-evidence.json`.

This technical PASS is not sufficient custody. The current restore-key blob is protected by
Windows DPAPI for the current user/profile. That prevents plaintext key exposure, but it does not
prove recovery after loss of the workstation or profile.

## Required owner decisions

The owner must name:

1. an independent protected destination for copy 2, outside the primary workstation failure
   domain;
2. the primary data custodian and a separate recovery custodian;
3. the approved secret escrow/password-manager/HSM target for portable recovery material; and
4. the retention period, including any legal or business audit hold.

A folder copied elsewhere on the same disk is not copy 2. No plaintext restore key may be put in
Git, chat, a PR, logs, a filename or an unencrypted note.

## Transfer and acceptance procedure

After the owner selects the destination, copy only the encrypted bundle and protected recovery
material through the approved channel. Recompute every ciphertext SHA-256 plus the bundle manifest
checksum at the destination. Run a recovery test outside production using a disposable isolated
target, then record the destination class, custodian roles, checksum parity, recovery result and
retention decision without recording credentials or storage secrets.

The proposed conservative retention floor is the later of 90 days after owner-accepted AH-03,
closure of V3 owner review, and all applicable audit holds. Deletion still needs a separate explicit
approval.

Until the machine-readable [custody record](v1-backup-custody.json) changes to owner-accepted with
two protected copies and portable recovery proof, backup custody remains a hard `NO-GO` gate.
