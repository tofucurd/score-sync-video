export function openingState(state, policy) {
  if(!policy || state.seconds>=policy.duration_seconds || state.seconds<0)return state;
  const t=Math.max(0,Math.min(1,state.seconds/policy.duration_seconds));
  const phase=policy.initial_phase+(1-policy.initial_phase)*t;
  const cap=phase*phase*phase*(10+phase*(-15+6*phase));
  return {...state,weights:Object.fromEntries(Object.entries(state.weights).map(([id,w])=>[id,Math.min(w,cap)]))};
}
