# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

## The engine's profile chooser (about:profilemanager), with protected profiles (#43).
## The same words as the Shell's unlock page (_locales: vault*).

nulavio-chooser-locked = Locked
nulavio-chooser-headline = This profile is locked
nulavio-chooser-explain = { $profile } keeps its files encrypted until you unlock it.
nulavio-chooser-password = Profile password
nulavio-chooser-recovery = Recovery code
nulavio-chooser-unlock = Unlock
nulavio-chooser-unlock-recovery = Unlock with recovery code
nulavio-chooser-use-keyring = Use my computer login
nulavio-chooser-use-recovery = Use the recovery code
nulavio-chooser-cancel = Cancel
nulavio-chooser-back = Back
nulavio-chooser-open = Open { $profile }
nulavio-chooser-unlocking = Unlocking…
nulavio-chooser-no-master-key = Nulavio has no master key: without one of this profile's ways to unlock it, nobody can open it, including Nulavio.
nulavio-chooser-wrong-password = That password did not unlock the profile.
nulavio-chooser-wrong-recovery = That recovery code did not unlock the profile.
nulavio-chooser-recovery-malformed = A recovery code has 28 letters and digits, in 7 groups of 4.
nulavio-chooser-recovery-required = This profile has no other way to unlock it now. Type its recovery code below.
nulavio-chooser-keyring-unavailable = Your computer login could not unlock it (the system keyring is not available or no longer has the key). Use the password or the recovery code.
nulavio-chooser-unavailable-headline = Protected profiles are not available
nulavio-chooser-storage-missing = This computer is missing what protected profiles need (gocryptfs and FUSE, or libsodium). Install them, then try again.
nulavio-chooser-gone-headline = This profile no longer exists
nulavio-chooser-gone = It may have been deleted. Nothing was changed.
nulavio-chooser-unread-headline = This profile could not be read
nulavio-chooser-unexpected = Something went wrong. Nothing was changed.
nulavio-chooser-recovery-finished = A recovery code replacement left unfinished earlier is now finished: the new code opens this profile, the previous one no longer does.
nulavio-chooser-recovery-undone = A recovery code replacement left unfinished earlier was undone: the previous code still opens this profile, the new one does not. To get a new one, replace it again under the profile's unlock methods.
nulavio-chooser-recovery-unsettled = A recovery code replacement left unfinished earlier could not be settled now: both codes still open this profile. It is tried again the next time the profile is unlocked from locked.
nulavio-chooser-recovery-unknown = A recovery code replacement left unfinished earlier may or may not have been settled: the key file could not be written or read back. The profile's unlock methods show which recovery code it has.
nulavio-chooser-not-recorded = The change was saved, but could not be recorded inside the profile. Lock the profile if it is open, then unlock it once to record it.
