---------------------------- MODULE CloneCopiesLatest ----------------------
EXTENDS Naturals, Sequences

CONSTANTS Writers, Contents, MaxVersion

VARIABLES docs, based, pc, base, want, receipt, copy

vars == <<docs, based, pc, base, want, receipt, copy>>

Version == Len(docs)

NoCopy == [from |-> 0, content |-> "none"]

Init ==
    /\ docs = <<>>
    /\ based = <<>>
    /\ pc = [w \in Writers |-> "idle"]
    /\ base = [w \in Writers |-> 0]
    /\ want = [w \in Writers |-> "none"]
    /\ receipt = [w \in Writers |-> 0]
    /\ copy = NoCopy

Propose(w, c) ==
    /\ pc[w] = "idle"
    /\ pc' = [pc EXCEPT ![w] = "proposed"]
    /\ base' = [base EXCEPT ![w] = Version]
    /\ want' = [want EXCEPT ![w] = c]
    /\ UNCHANGED <<docs, based, receipt, copy>>

Commit(w, sent) ==
    /\ pc[w] = "proposed"
    /\ receipt[w] = 0
    /\ Version < MaxVersion
    /\ base[w] = Version
    /\ sent = want[w]
    /\ docs' = Append(docs, sent)
    /\ based' = Append(based, base[w])
    /\ receipt' = [receipt EXCEPT ![w] = Version + 1]
    /\ pc' = [pc EXCEPT ![w] = "done"]
    /\ UNCHANGED <<base, want, copy>>

RefuseStale(w) ==
    /\ pc[w] = "proposed"
    /\ receipt[w] = 0
    /\ base[w] # Version
    /\ pc' = [pc EXCEPT ![w] = "stale"]
    /\ UNCHANGED <<docs, based, base, want, receipt, copy>>

Replay(w) ==
    /\ pc[w] = "done"
    /\ receipt[w] # 0
    /\ UNCHANGED vars

NextRequest(w) ==
    /\ pc[w] \in {"done", "stale", "proposed"}
    /\ pc' = [pc EXCEPT ![w] = "idle"]
    /\ receipt' = [receipt EXCEPT ![w] = 0]
    /\ UNCHANGED <<docs, based, base, want, copy>>

Clone(v) ==
    /\ copy = NoCopy
    /\ v \in 1..Version
    /\ copy' = [from |-> v, content |-> docs[Version]]
    /\ UNCHANGED <<docs, based, pc, base, want, receipt>>

Next ==
    \/ \E w \in Writers, c \in Contents : Propose(w, c) \/ Commit(w, c)
    \/ \E w \in Writers : RefuseStale(w) \/ Replay(w) \/ NextRequest(w)
    \/ \E v \in 1..MaxVersion : Clone(v)

Spec == Init /\ [][Next]_vars

NoLostUpdate == \A v \in 1..Version : based[v] = v - 1

CommittedIsProposed == \A w \in Writers : receipt[w] # 0 => docs[receipt[w]] = want[w]

ReceiptNamesAStoredVersion == \A w \in Writers : receipt[w] <= Version

CloneIsTheNamedVersion == copy # NoCopy => copy.content = docs[copy.from]
=============================================================================
