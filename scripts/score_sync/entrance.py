"""Optional delivery lead-in, separate from the reviewed musical clock."""
from pathlib import Path
import hashlib
import math


def sampled_noise_prefix(source, target, *, duration_seconds, seed_seconds,
                         crossfade_seconds=.02, edge_fade_seconds=.12, gain=1.):
    """Prepend an explicitly requested sample of room noise; copy source PCM.

    The caller selects an actually silent seed interval. This does not detect
    silence and must not be enabled just to hide a faulty alignment.
    """
    import numpy as np
    import soundfile as sf
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve() or target.exists():
        raise ValueError('Use a new destination; never overwrite source or a delivery')
    a, z = seed_seconds
    if not all(math.isfinite(v) for v in (duration_seconds, a, z, crossfade_seconds, edge_fade_seconds, gain)):
        raise ValueError('Non-finite lead-in parameter')
    if not (duration_seconds > 0 and 0 <= a < z and 0 < crossfade_seconds < z-a
            and 0 <= edge_fade_seconds <= duration_seconds/2 and gain >= 0):
        raise ValueError('Invalid lead-in, seed, crossfade or fade interval')
    with sf.SoundFile(source) as src:
        if src.subtype not in ('PCM_16', 'PCM_24', 'PCM_32') or z > len(src)/src.samplerate:
            raise ValueError('Use integer PCM and an in-range, reviewed seed')
        rate, channels, subtype, original_samples = src.samplerate, src.channels, src.subtype, len(src)
        n, cross, fade = round(duration_seconds*rate), round(crossfade_seconds*rate), round(edge_fade_seconds*rate)
        src.seek(round(a*rate)); seed = src.read(round((z-a)*rate), dtype='float64', always_2d=True)
        if not 0 < cross < len(seed) or n < 1:
            raise ValueError('Seed/crossfade must contain enough samples')
        noise = seed.copy(); ramp = np.linspace(0, 1, cross, endpoint=False)[:, None]
        while len(noise) < n:
            noise = np.concatenate((noise[:-cross], noise[-cross:]*(1-ramp)+seed[:cross]*ramp, seed[cross:]))
        noise = noise[:n].copy()*gain
        if fade:
            noise[:fade] *= np.linspace(0, 1, fade)[:, None]
            noise[-fade:] *= np.linspace(1, 0, fade)[:, None]
        src.seek(0); original = hashlib.sha256()
        target.parent.mkdir(parents=True, exist_ok=True)
        with sf.SoundFile(target, 'w', samplerate=rate, channels=channels, subtype=subtype, format='WAV') as dst:
            dst.write(noise)
            for block in src.blocks(blocksize=65536, dtype='int32'):
                original.update(block.tobytes()); dst.write(block)
    copied = hashlib.sha256()
    with sf.SoundFile(target) as out:
        if len(out) != original_samples+n:
            raise ValueError('Lead-in sample count differs')
        out.seek(n)
        for block in out.blocks(blocksize=65536, dtype='int32'):
            copied.update(block.tobytes())
    if original.digest() != copied.digest():
        raise ValueError('Original PCM after the prefix changed')
    return {'duration_seconds': n/rate, 'prefix_samples': n, 'sample_rate': rate,
            'channels': channels, 'bits': int(subtype.split('_')[1]),
            'source_samples': original_samples, 'output_samples': original_samples+n,
            'seed_original_seconds': [a, z], 'loop_crossfade_seconds': crossfade_seconds,
            'edge_fade_seconds': edge_fade_seconds, 'gain': gain,
            'original_decoded_int32_sha256': original.hexdigest(),
            'post_prefix_decoded_int32_sha256': copied.hexdigest()}


def make_delivery_frame(bundle, *, fps, prefix_seconds, animation_seconds, initial_phase=.315):
    """Return an absolute-frame function; retain all source-aligned timing."""
    from . import visual
    if not (fps > 0 and 0 < animation_seconds < prefix_seconds and 0 <= initial_phase <= 1):
        raise ValueError('Entrance needs an animation followed by a settled hold')
    events = {e['id']: e for e in bundle['score']['events']}
    settle = min(n['start'] for n in bundle['notes'] if not events[n['id']].get('grace'))
    weights = visual.frame_state(bundle, settle)['weights']
    initial = visual.smooth(initial_phase)

    def frame(index):
        elapsed = index/fps
        source_time = max(0., elapsed-prefix_seconds)
        result = visual.frame_state(bundle, source_time)
        result['delivery_entrance'] = True
        if elapsed < prefix_seconds:
            progress = visual.smooth(elapsed/animation_seconds)
            weight = initial+(1-initial)*progress
            result['weights'] = {k: w*weight for k, w in weights.items()}
            result['opening_layout_blend'] = {'progress': progress, 'initial_weight': initial, 'target_weights': weights}
            result['highlights'] = {}
        elif source_time < settle:
            result['weights'] = dict(weights)
        return result
    return frame
