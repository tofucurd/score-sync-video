"""Complete source-route tempo cuts, including those exactly on fit boundaries."""
import math

def complete_source_tempo_boundaries(start,end,tempo_events,profiles):
    at_q={}
    for row in sorted(tempo_events,key=lambda r:float(r['q'])):
        at_q[float(row['q'])]=row.get('tempo_metadata')
    last=None;have_last=False;cuts=[];transitions=[]
    for q,tempo in sorted(at_q.items()):
        value=float(tempo) if tempo is not None and math.isfinite(float(tempo)) and float(tempo)>0 else None
        changed=have_last and (last is None or value is None or abs(value-last)>1e-9)
        if changed and start<q<end:
            cuts.append(q);transitions.append({'q':q,'from_tempo_metadata':last,'to_tempo_metadata':value})
        last=value;have_last=True
    prior=sorted({float(q) for p in profiles for q in p['effective_tempo_boundaries_q']})
    return cuts,{'old_block_interior_cuts':prior,'whole_source_cuts':cuts,'previously_omitted_cuts':[q for q in cuts if q not in prior],'source_transitions':transitions,'principle':'A physical source tempo boundary is not removed when it coincides with an evidence-fit segment endpoint. Relative source metadata does not set a recording clock.'}

