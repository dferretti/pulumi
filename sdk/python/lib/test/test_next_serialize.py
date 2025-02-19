# Copyright 2016-2018, Pulumi Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import asyncio
import unittest
from typing import Any, Dict, List, Mapping, Optional, Sequence

from google.protobuf import struct_pb2
from pulumi.resource import ComponentResource, CustomResource
from pulumi.runtime import rpc, known_types, settings
from pulumi import Input, Output, UNKNOWN, input_type
from pulumi.asset import (
    FileAsset,
    RemoteAsset,
    StringAsset,
    AssetArchive,
    FileArchive,
    RemoteArchive
)
import pulumi


class TestCustomResource(CustomResource):
    def __init__(self, urn):
        self.__dict__["urn"] = Output.from_input(urn)
        self.__dict__["id"] = Output.from_input("id")

class TestComponentResource(ComponentResource):
    def __init__(self, urn):
        self.__dict__["urn"] = Output.from_input(urn)

def async_test(coro):
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(coro(*args, **kwargs))
        loop.close()
    return wrapper


class NextSerializationTests(unittest.TestCase):
    @async_test
    async def test_list(self):
        test_list = [1, 2, 3]
        props = await rpc.serialize_property(test_list, [])
        self.assertEqual(test_list, props)

    @async_test
    async def test_future(self):
        fut = asyncio.Future()
        fut.set_result(42)
        prop = await rpc.serialize_property(fut, [])
        self.assertEqual(42, prop)

    @async_test
    async def test_coro(self):
        async def fun():
            await asyncio.sleep(0.1)
            return 42

        prop = await rpc.serialize_property(fun(), [])
        self.assertEqual(42, prop)

    @async_test
    async def test_dict(self):
        fut = asyncio.Future()
        fut.set_result(99)
        test_dict = {"a": 42, "b": fut}
        prop = await rpc.serialize_property(test_dict, [])
        self.assertDictEqual({"a": 42, "b": 99}, prop)

    @async_test
    async def test_custom_resource(self):
        fake_urn = "urn:pulumi:mystack::myproject::my:mod:Fake::fake"
        res = TestCustomResource(fake_urn)

        settings.SETTINGS.feature_support["resourceReferences"] = False
        deps = []
        prop = await rpc.serialize_property(res, deps)
        self.assertListEqual([res], deps)
        self.assertEqual("id", prop)

        settings.SETTINGS.feature_support["resourceReferences"] = True
        deps = []
        prop = await rpc.serialize_property(res, deps)
        self.assertListEqual([res], deps)
        self.assertEqual(rpc._special_resource_sig, prop[rpc._special_sig_key])
        self.assertEqual(fake_urn, prop["urn"])
        self.assertEqual("id", prop["id"])

    @async_test
    async def test_component_resource(self):
        fake_urn = "urn:pulumi:mystack::myproject::my:mod:Fake::fake"
        res = TestComponentResource(fake_urn)

        settings.SETTINGS.feature_support["resourceReferences"] = False
        deps = []
        prop = await rpc.serialize_property(res, deps)
        self.assertListEqual([res], deps)
        self.assertEqual(fake_urn, prop)

        settings.SETTINGS.feature_support["resourceReferences"] = True
        deps = []
        prop = await rpc.serialize_property(res, deps)
        self.assertListEqual([res], deps)
        self.assertEqual(rpc._special_resource_sig, prop[rpc._special_sig_key])
        self.assertEqual(fake_urn, prop["urn"])

    @async_test
    async def test_string_asset(self):
        asset = StringAsset("Python 3 is cool")
        prop = await rpc.serialize_property(asset, [])
        self.assertEqual(rpc._special_asset_sig, prop[rpc._special_sig_key])
        self.assertEqual("Python 3 is cool", prop["text"])

    @async_test
    async def test_file_asset(self):
        asset = FileAsset("hello.txt")
        prop = await rpc.serialize_property(asset, [])
        self.assertEqual(rpc._special_asset_sig, prop[rpc._special_sig_key])
        self.assertEqual("hello.txt", prop["path"])

    @async_test
    async def test_remote_asset(self):
        asset = RemoteAsset("https://pulumi.com")
        prop = await rpc.serialize_property(asset, [])
        self.assertEqual(rpc._special_asset_sig, prop[rpc._special_sig_key])
        self.assertEqual("https://pulumi.com", prop["uri"])

    @async_test
    async def test_output(self):
        existing = TestCustomResource("existing-dependency")
        res = TestCustomResource("some-dependency")
        fut = asyncio.Future()
        fut.set_result(42)
        known_fut = asyncio.Future()
        known_fut.set_result(True)
        out = Output({res}, fut, known_fut)

        deps = [existing]
        prop = await rpc.serialize_property(out, deps)
        self.assertListEqual(deps, [existing, res])
        self.assertEqual(42, prop)

        known_fut = asyncio.Future()
        known_fut.set_result(False)
        out = Output(set(), fut, known_fut)

        # For compatibility, future() should still return 42 even if the value is unknown.
        prop = await out.future()
        self.assertEqual(42, prop)

        fut = asyncio.Future()
        fut.set_result(UNKNOWN)
        known_fut = asyncio.Future()
        known_fut.set_result(True)
        out = Output(set(), fut, known_fut)

        # For compatibility, is_known() should return False and future() should return None when the value contains
        # first-class unknowns.
        self.assertEqual(False, await out.is_known())
        self.assertEqual(None, await out.future())

        # If the caller of future() explicitly accepts first-class unknowns, they should be present in the result.
        self.assertEqual(UNKNOWN, await out.future(with_unknowns=True))

    @async_test
    async def test_output_all(self):
        res = TestCustomResource("some-resource")
        fut = asyncio.Future()
        fut.set_result(42)
        known_fut = asyncio.Future()
        known_fut.set_result(True)
        out = Output({res}, fut, known_fut)

        other = Output.from_input(99)
        combined = Output.all(out, other)
        deps = []
        prop = await rpc.serialize_property(combined, deps)
        self.assertListEqual(deps, [res])
        self.assertEqual([42, 99], prop)

    @async_test
    async def test_output_all_composes_dependencies(self):
        res = TestCustomResource("some-resource")
        fut = asyncio.Future()
        fut.set_result(42)
        known_fut = asyncio.Future()
        known_fut.set_result(True)
        out = Output({res}, fut, known_fut)

        other = TestCustomResource("some-other-resource")
        other_fut = asyncio.Future()
        other_fut.set_result(99)
        other_known_fut = asyncio.Future()
        other_known_fut.set_result(True)
        other_out = Output({other}, other_fut, other_known_fut)

        combined = Output.all(out, other_out)
        deps = []
        prop = await rpc.serialize_property(combined, deps)
        self.assertSetEqual(set(deps), {res, other})
        self.assertEqual([42, 99], prop)

    @async_test
    async def test_output_all_known_if_all_are_known(self):
        res = TestCustomResource("some-resource")
        fut = asyncio.Future()
        fut.set_result(42)
        known_fut = asyncio.Future()
        known_fut.set_result(True)
        out = Output({res}, fut, known_fut)

        other = TestCustomResource("some-other-resource")
        other_fut = asyncio.Future()
        other_fut.set_result(UNKNOWN) # <- not known
        other_known_fut = asyncio.Future()
        other_known_fut.set_result(False)
        other_out = Output({other}, other_fut, other_known_fut)

        combined = Output.all(out, other_out)
        deps = []
        prop = await rpc.serialize_property(combined, deps)
        self.assertSetEqual(set(deps), {res, other})

        # The contents of the list are unknown if any of the Outputs used to
        # create it were unknown.
        self.assertEqual(rpc.UNKNOWN, prop)


    @async_test
    async def test_unknown_output(self):
        res = TestCustomResource("some-dependency")
        fut = asyncio.Future()
        fut.set_result(None)
        known_fut = asyncio.Future()
        known_fut.set_result(False)
        out = Output({res}, fut, known_fut)
        deps = []
        prop = await rpc.serialize_property(out, deps)
        self.assertListEqual(deps, [res])
        self.assertEqual(rpc.UNKNOWN, prop)

    @async_test
    async def test_asset_archive(self):
        archive = AssetArchive({
            "foo": StringAsset("bar")
        })

        deps = []
        prop = await rpc.serialize_property(archive, deps)
        self.assertDictEqual({
            rpc._special_sig_key: rpc._special_archive_sig,
            "assets": {
                "foo": {
                    rpc._special_sig_key: rpc._special_asset_sig,
                    "text": "bar"
                }
            }
        }, prop)

    @async_test
    async def test_remote_archive(self):
        asset = RemoteArchive("https://pulumi.com")
        prop = await rpc.serialize_property(asset, [])
        self.assertEqual(rpc._special_archive_sig, prop[rpc._special_sig_key])
        self.assertEqual("https://pulumi.com", prop["uri"])

    @async_test
    async def test_file_archive(self):
        asset = FileArchive("foo.tar.gz")
        prop = await rpc.serialize_property(asset, [])
        self.assertEqual(rpc._special_archive_sig, prop[rpc._special_sig_key])
        self.assertEqual("foo.tar.gz", prop["path"])

    @async_test
    async def test_bad_inputs(self):
        class MyClass:
            def __init__(self):
                self.prop = "oh no!"

        error = None
        try:
            prop = await rpc.serialize_property(MyClass(), [])
        except ValueError as err:
            error = err

        self.assertIsNotNone(error)
        self.assertEqual("unexpected input of type MyClass", str(error))

    @async_test
    async def test_string(self):
        # Ensure strings are serialized as strings (and not sequences).
        prop = await rpc.serialize_property("hello world", [])
        self.assertEqual("hello world", prop)

    @async_test
    async def test_unsupported_sequences(self):
        cases = [
            ("hi", 42),
            range(10),
            memoryview(bytes(10)),
            bytes(10),
            bytearray(10),
        ]

        for case in cases:
            with self.assertRaises(ValueError):
                await rpc.serialize_property(case, [])

    @async_test
    async def test_distinguished_unknown_output(self):
        fut = asyncio.Future()
        fut.set_result(UNKNOWN)
        known_fut = asyncio.Future()
        known_fut.set_result(True)
        out = Output(set(), fut, known_fut)
        self.assertFalse(await out.is_known())

        fut = asyncio.Future()
        fut.set_result(["foo", UNKNOWN])
        out = Output(set(), fut, known_fut)
        self.assertFalse(await out.is_known())

        fut = asyncio.Future()
        fut.set_result({"foo": "foo", "bar": UNKNOWN})
        out = Output(set(), fut, known_fut)
        self.assertFalse(await out.is_known())

    def create_output(self, val: Any, is_known: bool, is_secret: Optional[bool] = None):
        fut = asyncio.Future()
        fut.set_result(val)
        known_fut = asyncio.Future()
        known_fut.set_result(is_known)
        if is_secret is not None:
            is_secret_fut = asyncio.Future()
            is_secret_fut.set_result(True)
            return Output(set(), fut, known_fut, is_secret_fut)
        return Output(set(), fut, known_fut)

    @async_test
    async def test_apply_can_run_on_known_value_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: v + 1)

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), 1)

    @async_test
    async def test_apply_can_run_on_known_awaitable_value_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True)

        def apply(v):
            fut = asyncio.Future()
            fut.set_result("inner")
            return fut
        r = out.apply(apply)

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_can_run_on_known_known_output_value_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=True))

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_can_run_on_known_unknown_output_value_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=False))

        self.assertFalse(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_produces_unknown_default_on_unknown_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: v + 1)

        self.assertFalse(await r.is_known())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_produces_unknown_default_on_unknown_awaitable_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False)

        def apply(v):
            fut = asyncio.Future()
            fut.set_result("inner")
            return fut
        r = out.apply(apply)

        self.assertFalse(await r.is_known())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_produces_unknown_default_on_unknown_known_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: self.create_output("inner", is_known=True))

        self.assertFalse(await r.is_known())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_produces_unknown_default_on_unknown_unknown_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: self.create_output("inner", is_known=False))

        self.assertFalse(await r.is_known())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_preserves_secret_on_known_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True, is_secret=True)
        r = out.apply(lambda v: v + 1)

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), 1)

    @async_test
    async def test_apply_preserves_secret_on_known_awaitable_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True, is_secret=True)

        def apply(v):
            fut = asyncio.Future()
            fut.set_result("inner")
            return fut
        r = out.apply(apply)

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_known_known_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True, is_secret=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=True))

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_known_unknown_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True, is_secret=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=False))

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_unknown_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False, is_secret=True)
        r = out.apply(lambda v: v + 1)

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_preserves_secret_on_unknown_awaitable_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False, is_secret=True)

        def apply(v):
            fut = asyncio.Future()
            fut.set_result("inner")
            return fut
        r = out.apply(apply)

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_preserves_secret_on_unknown_known_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False, is_secret=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=True))

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_preserves_secret_on_unknown_unknown_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False, is_secret=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=False))

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_propagates_secret_on_known_known_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=True, is_secret=True))

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_propagates_secret_on_known_unknown_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=False, is_secret=True))

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_does_not_propagate_secret_on_unknown_known_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: self.create_output("inner", is_known=True, is_secret=True))

        self.assertFalse(await r.is_known())
        self.assertFalse(await r.is_secret())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_does_not_propagate_secret_on_unknown_unknown_output_during_preview(self):
        settings.SETTINGS.dry_run = True

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: self.create_output("inner", is_known=False, is_secret=True))

        self.assertFalse(await r.is_known())
        self.assertFalse(await r.is_secret())
        self.assertEqual(await r.future(), None)

    @async_test
    async def test_apply_can_run_on_known_value(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: v + 1)

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), 1)

    @async_test
    async def test_apply_can_run_on_known_awaitable_value(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True)

        def apply(v):
            fut = asyncio.Future()
            fut.set_result("inner")
            return fut
        r = out.apply(apply)

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_can_run_on_known_known_output_value(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=True))

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_can_run_on_known_unknown_output_value(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=False))

        self.assertFalse(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_produces_known_on_unknown(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: v + 1)

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), 1)

    @async_test
    async def test_apply_produces_known_on_unknown_awaitable(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False)

        def apply(v):
            fut = asyncio.Future()
            fut.set_result("inner")
            return fut
        r = out.apply(apply)

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_produces_known_on_unknown_known_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: self.create_output("inner", is_known=True))

        self.assertTrue(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_produces_unknown_on_unknown_unknown_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: self.create_output("inner", is_known=False))

        self.assertFalse(await r.is_known())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_known(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True, is_secret=True)
        r = out.apply(lambda v: v + 1)

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), 1)

    @async_test
    async def test_apply_preserves_secret_on_known_awaitable(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True, is_secret=True)

        def apply(v):
            fut = asyncio.Future()
            fut.set_result("inner")
            return fut
        r = out.apply(apply)

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_known_known_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True, is_secret=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=True))

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_known_unknown_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True, is_secret=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=False))

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_unknown(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False, is_secret=True)
        r = out.apply(lambda v: v + 1)

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), 1)

    @async_test
    async def test_apply_preserves_secret_on_unknown_awaitable(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False, is_secret=True)

        def apply(v):
            fut = asyncio.Future()
            fut.set_result("inner")
            return fut
        r = out.apply(apply)

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_unknown_known_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False, is_secret=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=True))

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_preserves_secret_on_unknown_unknown_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False, is_secret=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=False))

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_propagates_secret_on_known_known_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=True, is_secret=True))

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_propagates_secret_on_known_unknown_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=True)
        r = out.apply(lambda v: self.create_output("inner", is_known=False, is_secret=True))

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_propagates_secret_on_unknown_known_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: self.create_output("inner", is_known=True, is_secret=True))

        self.assertTrue(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_propagates_secret_on_unknown_unknown_output(self):
        settings.SETTINGS.dry_run = False

        out = self.create_output(0, is_known=False)
        r = out.apply(lambda v: self.create_output("inner", is_known=False, is_secret=True))

        self.assertFalse(await r.is_known())
        self.assertTrue(await r.is_secret())
        self.assertEqual(await r.future(), "inner")

    @async_test
    async def test_apply_unknown_output(self):
        out = self.create_output("foo", is_known=True)

        r1 = out.apply(lambda v: UNKNOWN)
        r2 = out.apply(lambda v: [v, UNKNOWN])
        r3 = out.apply(lambda v: {"v": v, "unknown": UNKNOWN})
        r4 = out.apply(lambda v: UNKNOWN).apply(lambda v: v, True)
        r5 = out.apply(lambda v: [v, UNKNOWN]).apply(lambda v: v, True)
        r6 = out.apply(lambda v: {"v": v, "unknown": UNKNOWN}).apply(lambda v: v, True)

        self.assertFalse(await r1.is_known())
        self.assertFalse(await r2.is_known())
        self.assertFalse(await r3.is_known())
        self.assertFalse(await r4.is_known())
        self.assertFalse(await r5.is_known())
        self.assertFalse(await r6.is_known())

    @async_test
    async def test_lifted_unknown(self):
        settings.SETTINGS.dry_run = True

        fut = asyncio.Future()
        fut.set_result(UNKNOWN)
        out = Output.from_input({ "foo": "foo", "bar": UNKNOWN, "baz": fut})

        self.assertFalse(await out.is_known())

        r1 = out["foo"]
        self.assertTrue(await r1.is_known())
        self.assertEqual(await r1.future(with_unknowns=True), "foo")

        r2 = out["bar"]
        self.assertFalse(await r2.is_known())
        self.assertEqual(await r2.future(with_unknowns=True), UNKNOWN)

        r3 = out["baz"]
        self.assertFalse(await r3.is_known())
        self.assertEqual(await r3.future(with_unknowns=True), UNKNOWN)

        r4 = out["baz"]["qux"]
        self.assertFalse(await r4.is_known())
        self.assertEqual(await r4.future(with_unknowns=True), UNKNOWN)

        out = Output.from_input([ "foo", UNKNOWN ])

        r5 = out[0]
        self.assertTrue(await r5.is_known())
        self.assertEqual(await r5.future(with_unknowns=True), "foo")

        r6 = out[1]
        self.assertFalse(await r6.is_known())
        self.assertEqual(await r6.future(with_unknowns=True), UNKNOWN)

        out = Output.all(Output.from_input("foo"), Output.from_input(UNKNOWN),
            Output.from_input([ Output.from_input(UNKNOWN), Output.from_input("bar") ]))

        self.assertFalse(await out.is_known())

        r7 = out[0]
        self.assertTrue(await r7.is_known())
        self.assertEqual(await r7.future(with_unknowns=True), "foo")

        r8 = out[1]
        self.assertFalse(await r8.is_known())
        self.assertEqual(await r8.future(with_unknowns=True), UNKNOWN)

        r9 = out[2]
        self.assertFalse(await r9.is_known())

        r10 = r9[0]
        self.assertFalse(await r10.is_known())
        self.assertEqual(await r10.future(with_unknowns=True), UNKNOWN)

        r11 = r9[1]
        self.assertTrue(await r11.is_known())
        self.assertEqual(await r11.future(with_unknowns=True), "bar")


    @async_test
    async def test_output_coros(self):
        # Ensure that Outputs function properly when the input value and is_known are coroutines. If the implementation
        # is not careful to wrap these coroutines in Futures, they will be awaited more than once and the runtime will
        # throw.
        async def value():
            await asyncio.sleep(0)
            return 42
        async def is_known():
            await asyncio.sleep(0)
            return True

        out = Output(set(), value(), is_known())

        self.assertTrue(await out.is_known())
        self.assertEqual(42, await out.future())
        self.assertEqual(42, await out.apply(lambda v: v).future())


class DeserializationTests(unittest.TestCase):
    def test_unsupported_sig(self):
        struct = struct_pb2.Struct()
        struct[rpc._special_sig_key] = "foobar"

        error = None
        try:
            rpc.deserialize_property(struct)
        except  AssertionError as err:
            error = err
        self.assertIsNotNone(error)

    def test_secret_push_up(self):
        secret_value = {rpc._special_sig_key: rpc._special_secret_sig, "value": "a secret value" }
        all_props = struct_pb2.Struct()
        all_props["regular"] = "a normal value"
        all_props["list"] = ["a normal value", "another value", secret_value]
        all_props["map"] = {"regular": "a normal value", "secret": secret_value}
        all_props["mapWithList"] = {"regular": "a normal value", "list": ["a normal value", secret_value]}
        all_props["listWithMap"] = [{"regular": "a normal value", "secret": secret_value}]


        val = rpc.deserialize_properties(all_props)
        self.assertEqual(all_props["regular"], val["regular"])

        self.assertIsInstance(val["list"], dict)
        self.assertEqual(val["list"][rpc._special_sig_key], rpc._special_secret_sig)
        self.assertEqual(val["list"]["value"][0], "a normal value")
        self.assertEqual(val["list"]["value"][1], "another value")
        self.assertEqual(val["list"]["value"][2], "a secret value")

        self.assertIsInstance(val["map"], dict)
        self.assertEqual(val["map"][rpc._special_sig_key], rpc._special_secret_sig)
        self.assertEqual(val["map"]["value"]["regular"], "a normal value")
        self.assertEqual(val["map"]["value"]["secret"], "a secret value")

        self.assertIsInstance(val["mapWithList"], dict)
        self.assertEqual(val["mapWithList"][rpc._special_sig_key], rpc._special_secret_sig)
        self.assertEqual(val["mapWithList"]["value"]["regular"], "a normal value")
        self.assertEqual(val["mapWithList"]["value"]["list"][0], "a normal value")
        self.assertEqual(val["mapWithList"]["value"]["list"][1], "a secret value")

        self.assertIsInstance(val["listWithMap"], dict)
        self.assertEqual(val["listWithMap"][rpc._special_sig_key], rpc._special_secret_sig)
        self.assertEqual(val["listWithMap"]["value"][0]["regular"], "a normal value")
        self.assertEqual(val["listWithMap"]["value"][0]["secret"], "a secret value")

    def test_internal_property(self):
        all_props = struct_pb2.Struct()
        all_props["a"] = "b"
        all_props["__defaults"] = []
        all_props["c"] = {"foo": "bar", "__defaults": []}
        all_props["__provider"] = "serialized_dynamic_provider"
        all_props["__other"] = "baz"

        val = rpc.deserialize_properties(all_props)
        self.assertEqual({
            "a": "b",
            "c": {"foo": "bar"},
            "__provider": "serialized_dynamic_provider",
        }, val)

@input_type
class FooArgs:
    first_arg: Input[str] = pulumi.property("firstArg")
    second_arg: Optional[Input[float]] = pulumi.property("secondArg")

    def __init__(self, first_arg: Input[str], second_arg: Optional[Input[float]]=None):
        pulumi.set(self, "first_arg", first_arg)
        pulumi.set(self, "second_arg", second_arg)

@input_type
class ListDictInputArgs:
    a: List[Input[str]]
    b: Sequence[Input[str]]
    c: Dict[str, Input[str]]
    d: Mapping[str, Input[str]]

    def __init__(self,
                 a: List[Input[str]],
                 b: Sequence[Input[str]],
                 c: Dict[str, Input[str]],
                 d: Mapping[str, Input[str]]):
        pulumi.set(self, "a", a)
        pulumi.set(self, "b", b)
        pulumi.set(self, "c", c)
        pulumi.set(self, "d", d)


@input_type
class BarArgs:
    tag_args: Input[dict] = pulumi.property("tagArgs")

    def __init__(self, tag_args: Input[dict]):
        pulumi.set(self, "tag_args", tag_args)


class InputTypeSerializationTests(unittest.TestCase):
    @async_test
    async def test_simple_input_type(self):
        it = FooArgs(first_arg="hello", second_arg=42)
        prop = await rpc.serialize_property(it, [])
        self.assertEqual({"firstArg": "hello", "secondArg": 42}, prop)

    @async_test
    async def test_list_dict_input_type(self):
        it = ListDictInputArgs(a=["hi"], b=["there"], c={"hello": "world"}, d={"foo": "bar"})
        prop = await rpc.serialize_property(it, [])
        self.assertEqual({
            "a": ["hi"],
            "b": ["there"],
            "c": {"hello": "world"},
            "d": {"foo": "bar"}
        }, prop)

    @async_test
    async def test_input_type_with_dict_property(self):
        def transformer(prop: str) -> str:
            return {
                "tag_args": "a",
                "tagArgs": "b",
                "foo_bar": "c",
            }.get(prop) or prop

        it = BarArgs({"foo_bar": "hello", "foo_baz": "world"})
        prop = await rpc.serialize_property(it, [], transformer)
        # Input type keys are not transformed, but keys of nested
        # dicts are still transformed.
        self.assertEqual({
            "tagArgs": {
                "c": "hello",
                "foo_baz": "world",
            },
        }, prop)
