"""Bind reviewed clocks to the precise score, route and recording they describe."""
from pathlib import Path
from .workflow import read,write,digest,movement_dir


def alignment_binding(cfg,movement):
    d=movement_dir(cfg,movement);score=read(d/'score.json');audio=read(d/'audio.json')
    source=digest(movement['score'])
    if source!=score['source_sha256']:raise ValueError(f'{movement["id"]}: prepared score differs from source; prepare again')
    if digest(movement['audio'])!=audio['source_sha256']:raise ValueError(f'{movement["id"]}: prepared audio differs from source; prepare again')
    if movement.get('audio_range')!=audio.get('audio_range'):
        raise ValueError(f'{movement["id"]}: prepared audio_range differs from requested range; prepare again')
    if movement.get('source_route') and movement['source_route']!=score['source_route']:
        raise ValueError(f'{movement["id"]}: performance route changed; prepare and align again')
    return {'schema':1,'score_sha256':digest(d/'score.json'),'source_score_sha256':source,
            'alignment_sha256':digest(d/'alignment.json'),'source_route':score['source_route'],
            'audio':{k:audio[k] for k in ['source_sha256','sample_rate','samples','channels','bits']},
            'audio_range':movement.get('audio_range')}


def write_alignment_binding(cfg,movement):
    binding=alignment_binding(cfg,movement)
    path=movement_dir(cfg,movement)/'alignment-inputs.json'
    # A reference may preserve the original serialization as part of its digest.
    if not path.exists() or read(path)!=binding:write(path,binding)
    return binding


def validate_alignment_binding(cfg,movement):
    path=movement_dir(cfg,movement)/'alignment-inputs.json'
    if not path.exists():raise ValueError(f'{movement["id"]}: missing alignment-inputs.json; establish source/recording identity before review')
    if read(path)!=alignment_binding(cfg,movement):
        raise ValueError(f'{movement["id"]}: alignment input binding changed; existing review cannot be reused')
