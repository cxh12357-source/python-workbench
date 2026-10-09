"""Exercise the backup transport, corruption handling, and size boundaries."""

import base64
import gzip
import json

import pytest

from server.backup_codec import (COMPRESSED_FORMAT, COMPRESSION_THRESHOLD,
                                 decode_backup, encode_backup)


def backup(text="我的学习笔记"):
    return {"format": "cs50p-workbench", "schema_version": 1,
            "state": {"current_unit": "week-0", "units": {"week-0": {"note": text}}},
            "project": {"files": {"project.py": "print('你好')\n"}},
            "attempts": []}


def envelope(data):
    return {"format": COMPRESSED_FORMAT, "schema_version": 1,
            "encoding": "gzip-base64", "data": data}


def test_small_backup_keeps_raw_json_and_all_input_forms_roundtrip():
    value = backup()
    output = encode_backup(value)
    assert json.loads(output)["format"] == "cs50p-workbench"
    assert decode_backup(output) == value
    assert decode_backup(output.encode("utf-8")) == value
    assert decode_backup(json.loads(output)) == value


def test_large_repeated_learning_text_roundtrips_without_dropping_history():
    value = backup("每天练习函数、循环与中文笔记。\n" * 40_000)
    value["attempts"] = [{"exercise_id": "week-0-ex-1", "code": "print('练习')\n" * 100}
                         for _ in range(1000)]
    assert len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > COMPRESSION_THRESHOLD
    output = encode_backup(value)
    encoded = json.loads(output)
    assert encoded["format"] == COMPRESSED_FORMAT
    assert encoded["encoding"] == "gzip-base64"
    assert decode_backup(output) == value
    assert decode_backup(encoded) == value


@pytest.mark.parametrize("data", ["%%%not-base64%%%", "a", "é", "", base64.b64encode(b"not gzip").decode()])
def test_malformed_base64_and_gzip_are_rejected(data):
    with pytest.raises(ValueError, match="损坏"):
        decode_backup(envelope(data))


@pytest.mark.parametrize("mutate", [
    lambda data: data[:-4],
    lambda data: data[:-8] + bytes([data[-8] ^ 1]) + data[-7:],
])
def test_truncated_and_checksum_corrupt_gzip_are_rejected(mutate):
    encoded = json.loads(encode_backup(backup(), compression_threshold=0))
    compressed = base64.b64decode(encoded["data"])
    encoded["data"] = base64.b64encode(mutate(compressed)).decode()
    with pytest.raises(ValueError, match="损坏"):
        decode_backup(encoded)


def test_unknown_encoding_and_version_are_rejected():
    value = envelope("unused")
    value["encoding"] = "zip-base64"
    with pytest.raises(ValueError, match="不受支持"):
        decode_backup(value)
    value["encoding"] = "gzip-base64"
    value["schema_version"] = 2
    with pytest.raises(ValueError, match="不受支持"):
        decode_backup(value)


def test_compression_bomb_is_rejected_with_bounded_read():
    raw = json.dumps(backup("a" * 1_000_000)).encode()
    value = envelope(base64.b64encode(gzip.compress(raw)).decode())
    with pytest.raises(ValueError, match="解压容量"):
        decode_backup(value, max_decompressed_bytes=4096)


def test_oversized_export_is_rejected_before_an_unrestorable_file_is_returned():
    # Use a small transport limit to verify the same behavior without big RAM use.
    value = backup("longer note")
    with pytest.raises(ValueError, match="未生成备份"):
        encode_backup(value, max_upload_bytes=64)
    with pytest.raises(ValueError, match="未生成备份"):
        encode_backup(value, compression_threshold=0, max_upload_bytes=64)
    with pytest.raises(ValueError, match="解压容量"):
        encode_backup(value, max_decompressed_bytes=64)


def test_actual_json_transport_and_decompressed_size_boundaries():
    value = backup()
    output = encode_backup(value)
    size = len(output.encode("utf-8"))
    assert encode_backup(value, max_upload_bytes=size, max_decompressed_bytes=size) == output
    assert decode_backup(output, max_upload_bytes=size, max_decompressed_bytes=size) == value
    with pytest.raises(ValueError, match="上传容量"):
        decode_backup(output, max_upload_bytes=size - 1)
    with pytest.raises(ValueError, match="解压容量"):
        decode_backup(output, max_decompressed_bytes=size - 1)


def test_compressed_export_fits_its_exact_transport_and_content_limits():
    value = backup("重复的内容\n" * 100)
    raw = encode_backup(value, compression_threshold=10_000)
    output = encode_backup(value, compression_threshold=0)
    kwargs = {"max_upload_bytes": len(output.encode("utf-8")),
              "max_decompressed_bytes": len(raw.encode("utf-8"))}
    assert encode_backup(value, compression_threshold=0, **kwargs) == output
    assert decode_backup(output, **kwargs) == value


@pytest.mark.parametrize("value", ["not JSON", b"\xff", "[]", {"format": "other", "schema_version": 1}])
def test_bad_json_or_unsupported_raw_format_is_rejected(value):
    with pytest.raises(ValueError):
        decode_backup(value)


def test_nested_compression_envelope_is_not_recursively_expanded():
    inner = json.dumps(envelope("anything")).encode()
    outer = envelope(base64.b64encode(gzip.compress(inner)).decode())
    with pytest.raises(ValueError, match="不支持|支持的"):
        decode_backup(outer)


def test_invalid_json_numbers_and_encoding_are_rejected():
    value = backup()
    value["state"]["invalid"] = float("nan")
    with pytest.raises(ValueError):
        encode_backup(value)
    with pytest.raises(ValueError):
        decode_backup(value)
    with pytest.raises(ValueError):
        decode_backup('{"format":"cs50p-workbench","schema_version":1,"number":NaN}')


@pytest.mark.parametrize("kwargs", [{"max_upload_bytes": 0}, {"max_decompressed_bytes": -1},
                                    {"compression_threshold": -1}])
def test_invalid_size_limits_are_rejected(kwargs):
    with pytest.raises(ValueError):
        encode_backup(backup(), **kwargs)
