"""Keep JSON backups small while bounding uploads and decompression."""

import base64
import binascii
import gzip
import io
import json
import zlib

RAW_FORMAT = "cs50p-workbench"
COMPRESSED_FORMAT = "cs50p-workbench-compressed"
COMPRESSION_THRESHOLD = 1024 * 1024
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 128 * 1024 * 1024


def _limits(max_upload_bytes, max_decompressed_bytes):
    if any(type(limit) is not int or limit <= 0
           for limit in (max_upload_bytes, max_decompressed_bytes)):
        raise ValueError("备份大小限制必须是正整数。")


def _serialize(value):
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("备份内容不是有效的 JSON 数据。") from error


def _parse(value):
    def reject_constant(_):
        raise ValueError("备份中不能包含非有限数字。")

    try:
        result = json.loads(value.decode("utf-8"), parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("备份不是有效的 UTF-8 JSON 文件。") from error
    if not isinstance(result, dict):
        raise ValueError("备份 JSON 必须是对象。")
    return result


def _raw_backup(value):
    if (not isinstance(value, dict) or value.get("format") != RAW_FORMAT
            or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1):
        raise ValueError("这不是支持的工作台备份格式。")
    return value


def encode_backup(value, *, compression_threshold=COMPRESSION_THRESHOLD,
                  max_upload_bytes=MAX_UPLOAD_BYTES,
                  max_decompressed_bytes=MAX_DECOMPRESSED_BYTES):
    """Return the exact JSON response text; successful exports can be decoded.

    The uncompressed backup keeps its original schema. Large backups are
    wrapped in a versioned JSON envelope containing gzip bytes as base64.
    Content validation of learner records remains the storage layer's job.
    """
    _limits(max_upload_bytes, max_decompressed_bytes)
    if type(compression_threshold) is not int or compression_threshold < 0:
        raise ValueError("备份压缩阈值必须是非负整数。")
    raw = _serialize(_raw_backup(value))
    if len(raw) > max_decompressed_bytes:
        raise ValueError("学习记录超过备份解压容量，请联系维护者调整备份容量。")
    if len(raw) > compression_threshold:
        data = base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")
        output = _serialize({"format": COMPRESSED_FORMAT, "schema_version": 1,
                             "encoding": "gzip-base64", "data": data})
    else:
        output = raw
    if len(output) > max_upload_bytes:
        raise ValueError("备份文件超过可恢复的上传容量，未生成备份。请联系维护者调整备份容量。")
    return output.decode("utf-8")


def decode_backup(value, *, max_upload_bytes=MAX_UPLOAD_BYTES,
                  max_decompressed_bytes=MAX_DECOMPRESSED_BYTES):
    """Decode raw or compressed JSON, reading at most the allowed size + 1.

    Accept an uploaded JSON object, UTF-8 bytes, or the JSON text returned by
    encode_backup. The HTTP layer must also enforce the actual upload size.
    """
    _limits(max_upload_bytes, max_decompressed_bytes)
    if isinstance(value, dict):
        uploaded = _serialize(value)
    elif isinstance(value, str):
        try:
            uploaded = value.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("备份不是有效的 UTF-8 JSON 文件。") from error
    elif isinstance(value, bytes):
        uploaded = value
    else:
        raise ValueError("备份必须是 JSON 对象或 UTF-8 JSON 文件。")
    if len(uploaded) > max_upload_bytes:
        raise ValueError("备份文件超过上传容量。")
    envelope = _parse(uploaded)
    if envelope.get("format") != COMPRESSED_FORMAT:
        if len(uploaded) > max_decompressed_bytes:
            raise ValueError("学习记录超过备份解压容量。")
        return _raw_backup(envelope)
    if (type(envelope.get("schema_version")) is not int
            or envelope["schema_version"] != 1
            or envelope.get("encoding") != "gzip-base64"):
        raise ValueError("压缩备份的版本或编码不受支持。")
    data = envelope.get("data")
    if not isinstance(data, str):
        raise ValueError("压缩备份缺少有效数据。")
    try:
        compressed = base64.b64decode(data, validate=True)
        if not compressed:
            raise ValueError("压缩内容为空。")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            raw = stream.read(max_decompressed_bytes + 1)
    except (binascii.Error, ValueError, OSError, EOFError, zlib.error) as error:
        raise ValueError("压缩备份已损坏，无法恢复。") from error
    if len(raw) > max_decompressed_bytes:
        raise ValueError("学习记录超过备份解压容量。")
    return _raw_backup(_parse(raw))
