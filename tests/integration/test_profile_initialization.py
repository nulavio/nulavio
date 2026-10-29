"""First profile-store creation must coexist with the trusted identity reader."""

from __future__ import annotations

import unittest

import harness
from test_profiles import chrome_async

MODULES = """
const {NulavioProfiles:P}=ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioProfiles.sys.mjs');
const {SelectableProfileService:S}=ChromeUtils.importESModule('resource:///modules/profiles/SelectableProfileService.sys.mjs');
const {NulavioRouting:R}=ChromeUtils.importESModule('resource://builtin-addons/nulavio-shell/modules/NulavioRouting.sys.mjs');
"""


@unittest.skipUnless(harness.nulavio_engine(), "profile-store initialization requires the built-in Shell")
class ProfileInitializationTest(unittest.TestCase):
    def setUp(self):
        self.session = harness.GeckoProfileSession(name="FirstStore")
        self.addCleanup(self.session.cleanup)
        self.m = self.session.start()

    def test_identity_read_during_first_store_creation_does_not_reset_the_store(self):
        self.check_read_during_setup("profile")

    def test_identity_read_during_first_routing_write_does_not_reset_the_store(self):
        self.check_read_during_setup("routing")

    def test_first_routing_write_and_profile_creation_share_the_store(self):
        self.check_read_during_setup("routing-and-profile")

    def check_read_during_setup(self, operation):
        result = chrome_async(
            self.m,
            MODULES
            + """
          await P.temporaryState(); await S.init();
          if(S.currentProfile) throw new Error('fixture already has a profile group');
          const originalSetup=S.initProfilesData, originalInit=S.init;
          let entered,release,holding=false,readCalledInit=false;
          const started=new Promise(r=>entered=r),held=new Promise(r=>release=r);
          S.initProfilesData=async function(...args){
            await originalSetup.apply(this,args);holding=true;entered();await held;
          };
          S.init=function(...args){
            if(holding) readCalledInit=true;
            return originalInit.apply(this,args);
          };
          let creation;
          const operation=args[0].startsWith('routing')
            ? R.setEnabled(false).then(()=>({shared:true}))
            : P.create({name:'First additional profile',templateId:'work'}).then(id=>({id}));
          const made=operation.then(value=>creation=value,error=>creation={error:error.message});
          try {
            await started;
            const extra=args[0]==='routing-and-profile'
              ? P.create({name:'Concurrent additional profile'}).then(id=>({id}),error=>({error:error.message}))
              : Promise.resolve(null);
            const read=P.list();
            // Let the actual reader enter the service, if it is not waiting for
            // the first setup. No database or profile API result is mocked.
            await new Promise(resolve=>Services.tm.dispatchToMainThread(resolve));
            if(readCalledInit) await read;
            holding=false;release();
            await made;const snapshot=await read;
            const concurrent=await extra,final=await P.list();
            return {creation,concurrent,readHadCurrent:snapshot.profiles.some(p=>p.isCurrent),
              initialized:S.initialized,routingEnabled:R.enabled(),
              profiles:final.profiles.map(p=>({id:p.id,name:p.name,isCurrent:p.isCurrent}))};
          } finally {
            release();S.initProfilesData=originalSetup;S.init=originalInit;
          }
        """,
            [operation],
        )
        self.assertNotIn("error", result, result)
        state = result["ok"]
        self.assertNotIn("error", state["creation"], state)
        self.assertTrue(state["initialized"] and state["readHadCurrent"], state)
        self.assertEqual(sum(p["isCurrent"] for p in state["profiles"]), 1)
        if operation == "profile":
            self.assertGreater(state["creation"]["id"], 0)
            self.assertTrue(
                any(p["id"] == state["creation"]["id"] and p["name"] == "First additional profile" for p in state["profiles"])
            )
        else:
            self.assertTrue(state["creation"]["shared"])
            self.assertFalse(state["routingEnabled"])
            if operation == "routing-and-profile":
                self.assertNotIn("error", state["concurrent"], state)
                self.assertGreater(state["concurrent"]["id"], 0)
                self.assertEqual(len(state["profiles"]), 2, state)
                self.assertTrue(any(p["id"] == state["concurrent"]["id"] for p in state["profiles"]))

    def test_failed_first_setup_does_not_poison_later_creation(self):
        result = chrome_async(
            self.m,
            MODULES
            + """
          await P.temporaryState(); await S.init();
          const original=S.initProfilesData;
          S.initProfilesData=async()=>{throw new Error('injected setup failure');};
          let failure;
          try {await P.create({name:'Not created'});}
          catch(error){failure=error.message;}
          finally{S.initProfilesData=original;}
          const id=await P.create({name:'Created after retry'});
          const profiles=(await P.list()).profiles;
          return {failure,id,names:profiles.map(p=>p.name),initialized:S.initialized};
        """,
        )
        self.assertNotIn("error", result, result)
        state = result["ok"]
        self.assertEqual(state["failure"], "injected setup failure")
        self.assertGreater(state["id"], 0)
        self.assertTrue(state["initialized"])
        self.assertIn("Created after retry", state["names"])
        self.assertNotIn("Not created", state["names"])
