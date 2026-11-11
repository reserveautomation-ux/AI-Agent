"""Turn finished work into agent evaluations, which drive clone/suspend/retire."""

from psycopg import AsyncConnection


async def refresh_evaluations(
    conn: AsyncConnection, workspace_id: str, agent_ids: list[str]
) -> None:
    """Recompute 30-day outcomes for the given agents from their finished steps."""
    for agent_id in set(agent_ids):
        await conn.execute(
            """insert into public.agent_evaluations
                   (workspace_id, agent_id, agent_version, evaluation_window,
                    success_rate, quality_score, cost_usd, p50_latency_ms, sample_size)
               select %(ws)s, %(agent)s, a.version,
                      tstzrange(now() - interval '30 days', now()),
                      avg(case when t.status = 'completed' and s.status = 'succeeded'
                               then 1.0 else 0.0 end),
                      avg(coalesce((t.verification ->> 'score')::numeric, 0)),
                      coalesce(sum(c.cost), 0),
                      percentile_cont(0.5) within group (
                          order by extract(epoch from s.completed_at - s.started_at) * 1000),
                      count(*)
               from public.task_steps s
               join public.tasks t on t.id = s.task_id
               join public.agents a on a.id = s.agent_id
               left join lateral (
                   select sum(cost_usd) as cost from public.llm_calls l
                   where l.task_id = t.id and l.agent_id = s.agent_id
               ) c on true
               where s.agent_id = %(agent)s and s.workspace_id = %(ws)s
                 and t.status in ('completed', 'failed', 'waiting_for_approval')
                 and s.status in ('succeeded', 'failed')
                 and s.completed_at > now() - interval '30 days'
               group by a.version
               having count(*) > 0""",
            {"ws": workspace_id, "agent": agent_id},
        )
