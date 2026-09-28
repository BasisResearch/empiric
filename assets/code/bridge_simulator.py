"""Glue-and-weld dynamics for the n-shaped-bridge environment.

Mechanism inferred from real probes on level 1 (see ./journal.md section 2):

* The bottle is a glue dispenser with a downward nozzle at (bx, by, bz - nozzle_drop).
  Glue is deposited on the upward-facing surface underneath the nozzle only; bringing the
  bottle alongside a vertical face does nothing (measured at 0.033 m and 0.012 m standoff).
* Which named face receives the glue depends on where over the block the nozzle sits.
  Over the middle of the up-facing area -> `glue_top`; over the +x/-x end region ->
  `glue_end_b` / `glue_end_a`.  For a block standing on end (pitch = -pi/2) the up-facing
  area IS an end face, so that end is the one that gets glued.
* Glue is a level that ramps up while the nozzle is held in place (observed 0 -> 0.2 -> 0.4
  -> 1.0 over the ~4-action dwell that MoveTo performs at its target).
* Two blocks whose opposing end faces come into contact, with glue on them, fuse into one
  rigid body and BOTH glue levels are consumed (observed 1.0 -> 0.0 at the weld instant).
  Observed welds formed on real contact, not merely on being placed 1.3 mm apart.

Glue levels and welds live in model memory (observation-driven); the welds are realised in
the engine through `restore_model_attachments`, which is what makes a welded assembly move
and collision-check as one held body.
"""

import numpy as np  # noqa: F401  (also pre-injected)

from predicators.code_sim_learning.fit_space import ParamSpec

BLOCK_TYPE = "block"
BOTTLE_TYPE = "bottle"
FACES = ("top", "end_a", "end_b")
_HALF = np.array([0.05, 0.025, 0.025])


def _rot(roll, pitch, yaw):
    """World-from-body rotation matrix for the recorded euler triple."""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _block_frame(feat):
    """Return (centre, rotation, half-extents) for one observed block."""
    centre = np.array([feat["x"], feat["y"], feat["z"]])
    rot = _rot(feat["roll"], feat["pitch"], feat["yaw"])
    half = np.array([feat.get("half_x", 0.05),
                     feat.get("half_y", 0.025),
                     feat.get("half_z", 0.025)])
    return centre, rot, half


def _up_axis(rot):
    """Which local axis points most nearly straight up, and its sign."""
    col_z = rot[2, :]  # world-z component of each local axis
    axis = int(np.argmax(np.abs(col_z)))
    return axis, float(np.sign(col_z[axis]) or 1.0)


def _dab_face(feat, nozzle, params):
    """Face name the nozzle would glue, or None.

    The nozzle must sit above the block's up-facing surface, within `dab_height` of it and
    inside its lateral extent (plus `dab_radius` of slop).  The face is the top face unless
    the hit point lies in the outer `1 - end_frac` fraction of the long (local x) axis, in
    which case it is the corresponding end face.  When the up-facing surface is itself an
    end face (a block standing on end), that end face is the one glued.
    """
    centre, rot, half = _block_frame(feat)
    axis, sign = _up_axis(rot)
    local = rot.T @ (nozzle - centre)
    height = sign * local[axis] - half[axis]
    if height < -1e-4 or height > params["dab_height"]:
        return None
    # lateral containment in the other two axes
    for other in range(3):
        if other == axis:
            continue
        if abs(local[other]) > half[other] + params["dab_radius"]:
            return None
    if axis == 0:
        return "end_b" if sign > 0 else "end_a"
    # up-facing area is a long face: pick top vs end from the position along local x
    if local[0] > params["end_frac"] * half[0]:
        return "end_b"
    if local[0] < -params["end_frac"] * half[0]:
        return "end_a"
    return "top"


def _end_point(feat, face):
    """World position of the centre of an end face, and its outward normal."""
    centre, rot, half = _block_frame(feat)
    sign = 1.0 if face == "end_b" else -1.0
    normal = sign * rot[:, 0]
    return centre + normal * half[0], normal


def _observed(observation, type_name):
    out = {}
    for obj in observation:
        if obj.type.name != type_name:
            continue
        out[obj.name] = {
            f: float(observation.get(obj, f))
            for f in obj.type.feature_names
        }
    return out


class BridgeGlueWeld(BaseSimulator):  # noqa: F821  (injected by the loader)

    AGENT_PARAM_SPECS = [
        # how fast a held nozzle deposits glue (level per action)
        # directly observed on level 1: the reading stepped 0 -> 0.2 -> 0.4 -> 1.0, so the
        # per-action deposit is ~0.2; the bounds keep the pose-residual fit from running away
        # to a degenerate value that the pose data cannot actually see.
        ParamSpec("glue_rate", 0.2, lo=0.05, hi=0.6),
        # lateral slop around the up-facing area that still catches the dab
        ParamSpec("dab_radius", 0.015, lo=0.002, hi=0.05),
        # how far above the surface the nozzle may sit and still deposit
        ParamSpec("dab_height", 0.02, lo=0.002, hi=0.06),
        # fraction of the half-length beyond which a dab counts as an end, not the top
        ParamSpec("end_frac", 0.55, lo=0.2, hi=0.95),
        # largest face-to-face gap that still cures into a weld
        ParamSpec("weld_gap", 0.006, lo=0.001, hi=0.025),
        # largest lateral (off-axis) offset of two mating end faces that still cures
        ParamSpec("weld_lateral", 0.02, lo=0.005, hi=0.045),
        # glue level required before a contact cures
        ParamSpec("cure_level", 0.15, lo=0.05, hi=0.9),
        # nozzle offset below the bottle origin
        ParamSpec("nozzle_drop", 0.03, lo=0.01, hi=0.05),
    ]

    # Scored quantities: the block poses, which is what the welds actually change.
    RESIDUAL_FEATURES = {BLOCK_TYPE: ["x", "y", "z", "roll", "pitch", "yaw"]}

    MODEL_STATE_INIT = {"glue": {}, "welds": [], "seen": False}

    # ---------------------------------------------------------------- memory

    # Generous slack used only to decide whether a REMEMBERED weld is still plausible.
    # It must be looser than the curing tolerances so observation noise on a genuinely
    # welded pair can never prune it.
    STALE_GAP = 0.035
    STALE_LATERAL = 0.045

    @classmethod
    def _pair_adjacency(cls, fa, fb):
        """Return (face_a, face_b) if the two blocks sit end-to-end, else None."""
        best = None
        for face_a in ("end_a", "end_b"):
            pa, na = _end_point(fa, face_a)
            for face_b in ("end_a", "end_b"):
                pb, nb = _end_point(fb, face_b)
                if float(na @ nb) > -0.85:
                    continue
                delta = pb - pa
                gap = abs(float(delta @ na))
                lateral = float(np.linalg.norm(delta - (delta @ na) * na))
                if gap <= cls.STALE_GAP and lateral <= cls.STALE_LATERAL:
                    if best is None or gap < best[2]:
                        best = (face_a, face_b, gap)
        return None if best is None else (best[0], best[1])

    @classmethod
    def update_model_state(cls, observation, model_state, params, action):
        blocks = _observed(observation, BLOCK_TYPE)
        bottles = _observed(observation, BOTTLE_TYPE)
        glue = model_state.setdefault("glue", {})
        welds = model_state.setdefault("welds", [])
        for name in blocks:
            glue.setdefault(name, {f: 0.0 for f in FACES})

        # 0. consistency: a weld is rigid, so its two blocks must still be end-adjacent in
        #    the current observation.  Any remembered pair that is not is stale (e.g. memory
        #    carried across episodes, or a joint that never really took) and is dropped.
        kept = []
        for pair in welds:
            a, b = pair[0], pair[1]
            if a not in blocks or b not in blocks:
                continue
            if cls._pair_adjacency(blocks[a], blocks[b]) is not None:
                kept.append(pair)
        welds[:] = kept

        # 1. trust the environment's own glue readings when they are present: they are
        #    observable features, so tracking a real episode needs no integration at all.
        for name, feat in blocks.items():
            for face in FACES:
                key = "glue_" + face
                if key in feat:
                    glue[name][face] = max(glue[name][face], float(feat[key]))

        # 2. dispense from a held bottle onto the surface under the nozzle.
        for feat in bottles.values():
            if feat.get("is_held", 0.0) < 0.5:
                continue
            nozzle = np.array([feat["x"], feat["y"],
                               feat["z"] - params["nozzle_drop"]])
            for name, bfeat in blocks.items():
                if bfeat.get("is_held", 0.0) > 0.5:
                    continue
                face = _dab_face(bfeat, nozzle, params)
                if face is not None:
                    glue[name][face] = min(1.0, glue[name][face]
                                           + params["glue_rate"])

        # 3. cure: opposing end faces in contact with glue on both fuse, consuming the glue.
        names = sorted(blocks)
        existing = {tuple(sorted(p)) for p in welds}
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if tuple(sorted((a, b))) in existing:
                    continue
                for fa in ("end_a", "end_b"):
                    pa, na = _end_point(blocks[a], fa)
                    for fb in ("end_a", "end_b"):
                        pb, nb = _end_point(blocks[b], fb)
                        if float(na @ nb) > -0.9:      # faces must oppose
                            continue
                        delta = pb - pa
                        gap = abs(float(delta @ na))
                        lateral = float(np.linalg.norm(delta - (delta @ na) * na))
                        if gap > params["weld_gap"]:
                            continue
                        if lateral > params["weld_lateral"]:
                            continue
                        if (glue[a][fa] < params["cure_level"]
                                or glue[b][fb] < params["cure_level"]):
                            continue
                        welds.append([a, b])
                        existing.add(tuple(sorted((a, b))))
                        glue[a][fa] = 0.0
                        glue[b][fb] = 0.0
                        break
                    else:
                        continue
                    break
        model_state["seen"] = True

    # ------------------------------------------------------------- dynamics

    def _weld_pairs(self):
        """Remembered welds, gated on the pair still being end-adjacent right now.

        The gate matters because remembered welds can be stale (memory reconstructed over a
        different episode).  A weld is rigid, so a remembered pair that is nowhere near
        end-to-end in the live scene cannot be real and must not be realised in the engine.
        """
        state = self.model_state or {}
        pairs = [(p[0], p[1]) for p in state.get("welds", [])]
        if not pairs:
            return []
        try:
            blocks = _observed(self.get_observation(), BLOCK_TYPE)
        except Exception:  # pragma: no cover - keep raw memory if unreadable
            return pairs
        out = []
        for a, b in pairs:
            if a in blocks and b in blocks:
                if self._pair_adjacency(blocks[a], blocks[b]) is not None:
                    out.append((a, b))
        return out

    def _publish_links(self, force=False):
        """Register the inferred rigid links, but ONLY when the set changes.

        Re-registering an unchanged link every step re-creates the engine constraint at the
        latest relative transform, which pumps energy into the assembly (observed: a welded
        beam jittering off the table).  Publishing on change only keeps the joint rigid and
        the rollout stable.  The empty set is published too, so a pruned weld disappears.
        """
        pairs = self._weld_pairs()
        key = tuple(sorted(tuple(sorted(p)) for p in pairs))
        if force or key != getattr(self, "_published_links", None):
            self.restore_model_attachments(pairs)
            self._published_links = key

    def _domain_specific_step(self):
        self._publish_links()

    def restore_model_state(self):
        self._published_links = None
        self._publish_links(force=True)


RESIDUAL_ENV = BridgeGlueWeld
RESIDUAL_FEATURES = BridgeGlueWeld.RESIDUAL_FEATURES
