"""Measure only dimensions reachable through the saved modelspace placements."""

import math
from dataclasses import dataclass

from ezdxf.entities import Dimension, DXFGraphic
from ezdxf.math import Matrix44

MAX_BLOCK_DEPTH = 32
MAX_INSTANCES = 100_000


class BlockExpansionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def insert_placements(entity, *, limit=MAX_INSTANCES):
    """Collapse zero-spacing axes before ezdxf iterates the MINSERT grid."""
    dxf = entity.dxf
    if not all(
        math.isfinite(v) for v in (dxf.row_spacing, dxf.column_spacing, dxf.rotation)
    ):
        raise BlockExpansionError("BLOCK_ARRAY_INVALID")
    rows = dxf.row_count if dxf.row_spacing else 1
    columns = dxf.column_count if dxf.column_spacing else 1
    if rows * columns > limit:
        raise BlockExpansionError("BLOCK_INSTANCE_LIMIT")
    if rows * columns <= 1:
        yield entity
        return
    if rows != dxf.row_count or columns != dxf.column_count:
        entity = entity.copy()
        entity.dxf.row_count = rows
        entity.dxf.column_count = columns
    yield from entity.multi_insert()


@dataclass(frozen=True)
class EntityInstance:
    entity: DXFGraphic
    matrix: Matrix44
    insert_handles: tuple[str, ...]

    def measurement(self):
        # A normal entity copy clones its anonymous graphics block. A detached
        # attribute-only dimension avoids both that cost and source mutation.
        attrs = self.entity.dxfattribs()
        for key in ("handle", "owner", "geometry"):
            attrs.pop(key, None)
        dimension = Dimension.new(dxfattribs=attrs)
        dimension.transform(self.matrix)
        return dimension.get_measurement()


def collect_dimensions(doc, source_handles=()):
    """Return placed dimensions and explicit errors for incomplete traversal.

    Cache dimensions, inserts and requested source references per definition;
    large drawing blocks are not exploded. Repeated placements remain separate.
    """
    instances, errors, blocks, sources = [], [], {}, {}
    source_handles = set(source_handles)
    visited = 0
    exhausted = False

    def walk(entities, matrix, active, handles):
        nonlocal visited, exhausted
        for entity in entities:
            if exhausted:
                return
            kind = entity.dxftype()
            referenced = entity.dxf.handle in source_handles
            if kind not in {"DIMENSION", "INSERT"} and not referenced:
                continue
            visited += 1
            if visited > MAX_INSTANCES:
                errors.append({"code": "BLOCK_INSTANCE_LIMIT", "limit": MAX_INSTANCES})
                exhausted = True
                return
            if kind == "DIMENSION":
                instances.append(EntityInstance(entity, matrix, handles))
                continue
            if referenced:
                sources.setdefault(entity.dxf.handle, []).append(
                    EntityInstance(entity, matrix, handles)
                )
            if kind != "INSERT":
                continue
            handle = entity.dxf.handle
            name = entity.dxf.name
            key = name.casefold()
            if key in active:
                errors.append(
                    {"code": "BLOCK_REFERENCE_CYCLE", "handle": handle, "block": name}
                )
                continue
            if len(active) >= MAX_BLOCK_DEPTH:
                errors.append(
                    {
                        "code": "BLOCK_DEPTH_LIMIT",
                        "handle": handle,
                        "limit": MAX_BLOCK_DEPTH,
                    }
                )
                continue
            block = doc.blocks.get(name)
            if block is None:
                errors.append(
                    {"code": "BLOCK_REFERENCE_MISSING", "handle": handle, "block": name}
                )
                continue
            if key not in blocks:
                blocks[key] = tuple(
                    e
                    for e in block
                    if e.dxftype() in {"DIMENSION", "INSERT"}
                    or e.dxf.handle in source_handles
                )
            if not blocks[key]:
                continue
            try:
                placements = insert_placements(entity, limit=MAX_INSTANCES - visited)
                for placement in placements:
                    if exhausted:
                        return
                    # ezdxf uses row vectors: local placement precedes parent.
                    transform = placement.matrix44() @ matrix
                    walk(blocks[key], transform, active + (key,), handles + (handle,))
            except (ValueError, ArithmeticError) as exc:
                errors.append(
                    {
                        "code": exc.code
                        if isinstance(exc, BlockExpansionError)
                        else "BLOCK_TRANSFORM_INVALID",
                        "handle": handle,
                        "message": str(exc),
                    }
                )

    walk(doc.modelspace(), Matrix44(), (), ())
    return instances, sources, errors
