"""Creating dataset versions and reading their manifests.

A dataset version is never overwritten. A model version must trace back to
exactly the data it learned from; if a version could be replaced, the data
would be gone while the model that learned from it stayed registered.
"""

from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq

from . import splits
from .storage import Storage, dataset_manifest_key, raw_key


class DatasetVersionExistsError(Exception):
    """Raised when creating a dataset version under a name already taken.

    Example:
        try:
            publish_dataset(storage, "/tmp/data.parquet", "v1")
        except DatasetVersionExistsError:
            ...  # the API answers 409 and the operator picks another name
    """


def dataset_exists(storage: Storage, dataset_version: str) -> bool:
    """Tells whether a dataset version has already been created.

    Args:
        storage: where dataset versions live.
        dataset_version: the version name.

    Returns:
        True when raw data or a manifest exists under that name. Either one is
        enough: a half-written version still owns its name.

    Example:
        dataset_exists(storage, "v1")  # -> True once seeded
    """
    return storage.exists(raw_key(dataset_version)) or storage.exists(
        dataset_manifest_key(dataset_version)
    )


def publish_dataset(storage: Storage, local_parquet: str, dataset_version: str) -> dict:
    """Creates a dataset version from a local parquet file, with its manifest.

    The split points are computed here, once, from the whole file, and never
    again (CN-01).

    Args:
        storage: where to write.
        local_parquet: the parquet file holding the raw data, every column text.
        dataset_version: the new version's name. Must not exist yet.

    Returns:
        The manifest that was written.

    Raises:
        DatasetVersionExistsError: when the name is taken (CN-02).
        ValueError: when the data has no `listing_date` column or no record
            has a readable one, so no split point can be placed. Nothing is
            written in that case.

    Example:
        manifest = publish_dataset(storage, "/tmp/data.parquet", "v2")
        manifest["split_points"]["original"]["t2"]  # -> "2024-11-03"
    """
    if dataset_exists(storage, dataset_version):
        raise DatasetVersionExistsError(f"dataset version {dataset_version!r} already exists")
    if "listing_date" not in pq.read_schema(local_parquet).names:
        raise ValueError("the data has no listing_date column, so no split point can be placed")
    frame = pd.read_parquet(local_parquet, columns=["listing_date"])
    manifest = splits.build_manifest(dataset_version, frame["listing_date"], len(frame))
    storage.upload_file(local_parquet, raw_key(dataset_version))
    storage.write_json(manifest, dataset_manifest_key(dataset_version))
    return manifest


def publish_frame(storage: Storage, frame: pd.DataFrame, dataset_version: str, manifest: dict):
    """Creates a dataset version from a frame built inside the system.

    Used by the feedback pipeline, whose manifest (split points, lineage) is
    decided by the builder rather than computed from listing dates.

    Args:
        storage: where to write.
        frame: the data, every column text or None.
        dataset_version: the new version's name. Must not exist yet.
        manifest: the manifest to store with it.

    Returns:
        None.

    Raises:
        DatasetVersionExistsError: when the name is taken (CN-02).

    Example:
        publish_frame(storage, merged, "v1-fb1", manifest)
    """
    if dataset_exists(storage, dataset_version):
        raise DatasetVersionExistsError(f"dataset version {dataset_version!r} already exists")
    storage.write_parquet(frame, raw_key(dataset_version))
    storage.write_json(manifest, dataset_manifest_key(dataset_version))


def read_manifest(storage: Storage, dataset_version: str) -> dict:
    """Reads the manifest of a dataset version.

    Args:
        storage: where dataset versions live.
        dataset_version: the version name.

    Returns:
        The manifest dict.

    Raises:
        FileNotFoundError: when the version has no manifest.

    Example:
        read_manifest(storage, "v2")["lineage"]  # -> None for an upload
    """
    return storage.read_json(dataset_manifest_key(dataset_version))


def ensure_manifest(storage: Storage, dataset_version: str) -> dict:
    """Reads a version's manifest, creating it for versions made before manifests existed.

    Versions uploaded before split points were introduced have raw data but no
    manifest. Their split points are computed once, by the same rule an upload
    uses, and stored, so every later run reads the same ones.

    Args:
        storage: where dataset versions live.
        dataset_version: the version name.

    Returns:
        The manifest dict.

    Raises:
        FileNotFoundError: when the version has neither a manifest nor raw data.

    Example:
        ensure_manifest(storage, "v1")  # -> computed and written on first call
        ensure_manifest(storage, "v1")  # -> read back, identical, afterwards
    """
    try:
        return read_manifest(storage, dataset_version)
    except FileNotFoundError:
        pass
    frame = storage.read_parquet(raw_key(dataset_version), columns=["listing_date"])
    manifest = splits.build_manifest(dataset_version, frame["listing_date"], len(frame))
    storage.write_json(manifest, dataset_manifest_key(dataset_version))
    return manifest
