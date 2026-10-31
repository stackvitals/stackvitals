-- Copyright The Apache Software Foundation. Licensed under the Apache License, Version 2.0
-- (https://www.apache.org/licenses/LICENSE-2.0). From Apache DevLake (https://github.com/apache/incubator-devlake);
-- changed by StackVitals as described below. See NOTICE.
-- Apache DevLake's DORA dashboard (grafana/dashboards/DORA.json), its five main panels ported from MySQL to DuckDB.
-- The CTEs are DevLake's own; only the dialect changed: Grafana's time macros became {{FROM}} and {{TO}}, the project
-- variable {{PROJECT}}, the report variable {{REPORT}}; DATE() became CAST(... AS date), WEEKDAY() isodow() - 1,
-- date_format() strftime(), TIMESTAMPDIFF(MINUTE) whole elapsed minutes, double-quoted strings single-quoted.

-- panel: deployment_frequency
with last_few_calendar_months as(
-- construct the last few calendar months within the selected time period in the top-right corner
	SELECT CAST((TIMESTAMP '{{TO}}' - INTERVAL (H+T+U) DAY) AS date) as day
	FROM ( SELECT 0 H
			UNION ALL SELECT 100 UNION ALL SELECT 200 UNION ALL SELECT 300
		) H CROSS JOIN ( SELECT 0 T
			UNION ALL SELECT  10 UNION ALL SELECT  20 UNION ALL SELECT  30
			UNION ALL SELECT  40 UNION ALL SELECT  50 UNION ALL SELECT  60
			UNION ALL SELECT  70 UNION ALL SELECT  80 UNION ALL SELECT  90
		) T CROSS JOIN ( SELECT 0 U
			UNION ALL SELECT   1 UNION ALL SELECT   2 UNION ALL SELECT   3
			UNION ALL SELECT   4 UNION ALL SELECT   5 UNION ALL SELECT   6
			UNION ALL SELECT   7 UNION ALL SELECT   8 UNION ALL SELECT   9
		) U
	WHERE
		(TIMESTAMP '{{TO}}' - INTERVAL (H+T+U) DAY) > TIMESTAMP '{{FROM}}'
),

_production_deployment_days as(
	SELECT
		cdc.cicd_deployment_id as deployment_id,
		max(CAST(cdc.finished_date AS date)) as day
	FROM cicd_deployment_commits cdc
	JOIN project_mapping pm on cdc.cicd_scope_id = pm.row_id and pm."table" = 'cicd_scopes'
	WHERE
		pm.project_name in ('{{PROJECT}}')
		and cdc.result = 'SUCCESS'
		and cdc.environment = 'PRODUCTION'
	GROUP BY 1
),

_days_weekly_deploy as(
	SELECT
			CAST(last_few_calendar_months.day - INTERVAL (isodow(last_few_calendar_months.day) - 1) DAY AS date) as week,
			MAX(CASE WHEN _production_deployment_days.day is not null THEN 1 END) as weeks_deployed,
			COUNT(distinct _production_deployment_days.day) as days_deployed
	FROM
		last_few_calendar_months
		LEFT JOIN _production_deployment_days ON _production_deployment_days.day = last_few_calendar_months.day
	GROUP BY week
	),

_days_monthly_deploy as(
	SELECT
			CAST(last_few_calendar_months.day - INTERVAL (day(last_few_calendar_months.day) - 1) DAY AS date) as month,
			MAX(CASE WHEN _production_deployment_days.day is not null THEN 1 END) as months_deployed,
		  COUNT(distinct _production_deployment_days.day) as days_deployed
	FROM
		last_few_calendar_months
		LEFT JOIN _production_deployment_days ON _production_deployment_days.day = last_few_calendar_months.day
	GROUP BY month
	),

_days_six_months_deploy AS (
  SELECT
    month,
    SUM(days_deployed) OVER (
      ORDER BY month
      ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
    ) AS days_deployed_per_six_months,
    COUNT(months_deployed) OVER (
      ORDER BY month
      ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
    ) AS months_deployed_count,
    ROW_NUMBER() OVER (
      -- MySQL reads DATE_FORMAT(month, '%Y-%m') DIV 6 as the year DIV 6
      PARTITION BY year(month) // 6
      ORDER BY month DESC
    ) AS rn
  FROM _days_monthly_deploy
),

_median_number_of_deployment_days_per_week_ranks as(
	SELECT *, percent_rank() over(order by days_deployed) as ranks
	FROM _days_weekly_deploy
),

_median_number_of_deployment_days_per_week as(
	SELECT max(days_deployed) as median_number_of_deployment_days_per_week
	FROM _median_number_of_deployment_days_per_week_ranks
	WHERE ranks <= 0.5
),

_median_number_of_deployment_days_per_month_ranks as(
	SELECT *, percent_rank() over(order by days_deployed) as ranks
	FROM _days_monthly_deploy
),

_median_number_of_deployment_days_per_month as(
	SELECT max(days_deployed) as median_number_of_deployment_days_per_month
	FROM _median_number_of_deployment_days_per_month_ranks
	WHERE ranks <= 0.5
),

_days_per_six_months_deploy_by_filter AS (
SELECT
  month,
  days_deployed_per_six_months,
  months_deployed_count
FROM _days_six_months_deploy
WHERE rn%6 = 1
),

_median_number_of_deployment_days_per_six_months_ranks as(
	SELECT *, percent_rank() over(order by days_deployed_per_six_months) as ranks
	FROM _days_per_six_months_deploy_by_filter
),

_median_number_of_deployment_days_per_six_months as(
	SELECT min(days_deployed_per_six_months) as median_number_of_deployment_days_per_six_months, min(months_deployed_count) as is_collected
	FROM _median_number_of_deployment_days_per_six_months_ranks
	WHERE ranks >= 0.5
)

SELECT
  CASE
    WHEN ('{{REPORT}}') = '2023' THEN
			CASE
				WHEN median_number_of_deployment_days_per_week >= 5 THEN CONCAT(median_number_of_deployment_days_per_week, ' deployment days per week(elite)')
				WHEN median_number_of_deployment_days_per_week >= 1 THEN CONCAT(median_number_of_deployment_days_per_week, ' deployment days per week(high)')
				WHEN median_number_of_deployment_days_per_month >= 1 THEN CONCAT(median_number_of_deployment_days_per_month, ' deployment days per month(medium)')
				WHEN median_number_of_deployment_days_per_month < 1 and is_collected is not null THEN CONCAT(median_number_of_deployment_days_per_month, ' deployment days per month(low)')
				ELSE 'N/A. Please check if you have collected deployments.' END
	 	WHEN ('{{REPORT}}') = '2021' THEN
			CASE
				WHEN median_number_of_deployment_days_per_week >= 5 THEN CONCAT(median_number_of_deployment_days_per_week, ' deployment days per week(elite)')
				WHEN median_number_of_deployment_days_per_month >= 1 THEN CONCAT(median_number_of_deployment_days_per_month, ' deployment days per month(high)')
				WHEN median_number_of_deployment_days_per_six_months >= 1 THEN CONCAT(median_number_of_deployment_days_per_six_months, ' deployment days per six months(medium)')
				WHEN median_number_of_deployment_days_per_six_months < 1 and is_collected is not null THEN CONCAT(median_number_of_deployment_days_per_six_months, ' deployment days per six months(low)')
				ELSE 'N/A. Please check if you have collected deployments.' END
		ELSE 'Invalid dora report'
	END AS "Deployment Frequency"
FROM _median_number_of_deployment_days_per_week, _median_number_of_deployment_days_per_month, _median_number_of_deployment_days_per_six_months;

-- panel: lead_time
with _pr_stats as (
-- get the cycle time of PRs deployed by the deployments finished in the selected period
	SELECT
		distinct pr.id,
		ppm.pr_cycle_time
	FROM
		pull_requests pr
		join project_pr_metrics ppm on ppm.id = pr.id
		join project_mapping pm on pr.base_repo_id = pm.row_id and pm."table" = 'repos'
		join cicd_deployment_commits cdc on ppm.deployment_commit_id = cdc.id
	WHERE
	  pm.project_name in ('{{PROJECT}}')
		and pr.merged_date is not null
		and ppm.pr_cycle_time is not null
		and cdc.finished_date BETWEEN TIMESTAMP '{{FROM}}' AND TIMESTAMP '{{TO}}'
),

_median_change_lead_time_ranks as(
	SELECT *, percent_rank() over(order by pr_cycle_time) as ranks
	FROM _pr_stats
),

_median_change_lead_time as(
-- use median PR cycle time as the median change lead time
	SELECT max(pr_cycle_time) as median_change_lead_time
	FROM _median_change_lead_time_ranks
	WHERE ranks <= 0.5
)

SELECT
  CASE
    WHEN ('{{REPORT}}') = '2023' THEN
			CASE
				WHEN median_change_lead_time < 24 * 60 THEN CONCAT(round(median_change_lead_time/60,1), '(elite)')
				WHEN median_change_lead_time < 7 * 24 * 60 THEN CONCAT(round(median_change_lead_time/60,1), '(high)')
				WHEN median_change_lead_time < 30 * 24 * 60 THEN CONCAT(round(median_change_lead_time/60,1), '(medium)')
				WHEN median_change_lead_time >= 30 * 24 * 60 THEN CONCAT(round(median_change_lead_time/60,1), '(low)')
				ELSE 'N/A. Please check if you have collected deployments/pull_requests.'
				END
    WHEN ('{{REPORT}}') = '2021' THEN
		  CASE
				WHEN median_change_lead_time < 60 THEN CONCAT(round(median_change_lead_time/60,1), '(elite)')
				WHEN median_change_lead_time < 7 * 24 * 60 THEN CONCAT(round(median_change_lead_time/60,1), '(high)')
				WHEN median_change_lead_time < 180 * 24 * 60 THEN CONCAT(round(median_change_lead_time/60,1), '(medium)')
				WHEN median_change_lead_time >= 180 * 24 * 60 THEN CONCAT(round(median_change_lead_time/60,1), '(low)')
				ELSE 'N/A. Please check if you have collected deployments/pull_requests.'
				END
		ELSE 'Invalid dora report'
	END AS median_change_lead_time
FROM _median_change_lead_time;

-- panel: change_failure_rate
with _deployments as (
  SELECT
    cdc.cicd_deployment_id as deployment_id,
    max(cdc.finished_date) as deployment_finished_date
  FROM
    cicd_deployment_commits cdc
    JOIN project_mapping pm on cdc.cicd_scope_id = pm.row_id
    and pm."table" = 'cicd_scopes'
  WHERE
    pm.project_name in ('{{PROJECT}}')
    and cdc.result = 'SUCCESS'
    and cdc.environment = 'PRODUCTION'
  GROUP BY
    1
  HAVING
    max(cdc.finished_date) BETWEEN TIMESTAMP '{{FROM}}' AND TIMESTAMP '{{TO}}'
),
_failure_caused_by_deployments as (
  -- calculate the number of incidents caused by each deployment
  SELECT
    d.deployment_id,
    d.deployment_finished_date,
    count(
      distinct case
        when i.id is not null then d.deployment_id
        else null
      end
    ) as has_incident
  FROM
    _deployments d
    left join project_incident_deployment_relationships pim on d.deployment_id = pim.deployment_id
    left join incidents i on pim.id = i.id
  GROUP BY
    1,
    2
),
_change_failure_rate as (
  SELECT
    case
      when count(deployment_id) is null then null
      else sum(has_incident) / count(deployment_id)
    end as change_failure_rate
  FROM
    _failure_caused_by_deployments
),
_is_collected_data as(
  SELECT
    CASE
      WHEN COUNT(i.id) = 0
      AND COUNT(cdc.id) = 0 THEN 'No All'
      WHEN COUNT(i.id) = 0 THEN 'No Incidents'
      WHEN COUNT(cdc.id) = 0 THEN 'No Deployments'
    END AS is_collected
  FROM
    (
      SELECT
        1
    ) AS dummy
    LEFT JOIN incidents i ON 1 = 1
    LEFT JOIN cicd_deployment_commits cdc ON 1 = 1
)
SELECT
  CASE
    WHEN ('{{REPORT}}') = '2023' THEN CASE
      WHEN is_collected = 'No All' THEN 'N/A. Please check if you have collected deployments/incidents.'
      WHEN is_collected = 'No Incidents' THEN 'N/A. Please check if you have collected incidents.'
      WHEN is_collected = 'No Deployments' THEN 'N/A. Please check if you have collected deployments.'
      WHEN change_failure_rate <=.05 THEN CONCAT(round(change_failure_rate * 100, 1), '%(elite)')
      WHEN change_failure_rate <=.10 THEN CONCAT(round(change_failure_rate * 100, 1), '%(high)')
      WHEN change_failure_rate <=.15 THEN CONCAT(round(change_failure_rate * 100, 1), '%(medium)')
      WHEN change_failure_rate >.15 THEN CONCAT(round(change_failure_rate * 100, 1), '%(low)')
      ELSE 'N/A. Please check if you have collected deployments/incidents.'
    END
    WHEN ('{{REPORT}}') = '2021' THEN CASE
      WHEN is_collected = 'No All' THEN 'N/A. Please check if you have collected deployments/incidents.'
      WHEN is_collected = 'No Incidents' THEN 'N/A. Please check if you have collected incidents.'
      WHEN is_collected = 'No Deployments' THEN 'N/A. Please check if you have collected deployments.'
      WHEN change_failure_rate <=.15 THEN CONCAT(round(change_failure_rate * 100, 1), '%(elite)')
      WHEN change_failure_rate <=.20 THEN CONCAT(round(change_failure_rate * 100, 1), '%(high)')
      WHEN change_failure_rate <=.30 THEN CONCAT(round(change_failure_rate * 100, 1), '%(medium)')
      WHEN change_failure_rate >.30 THEN CONCAT(round(change_failure_rate * 100, 1), '%(low)')
      ELSE 'N/A. Please check if you have collected deployments/incidents.'
    END
    ELSE 'No data'
  END AS change_failure_rate
FROM
  _change_failure_rate,
  _is_collected_data;

-- panel: recovery
with _deployments as (
  SELECT
    cdc.cicd_deployment_id as deployment_id,
    max(cdc.finished_date) as deployment_finished_date
  FROM
    cicd_deployment_commits cdc
    JOIN project_mapping pm on cdc.cicd_scope_id = pm.row_id
    and pm."table" = 'cicd_scopes'
  WHERE
    pm.project_name in ('{{PROJECT}}')
    and cdc.result = 'SUCCESS'
    and cdc.environment = 'PRODUCTION'
  GROUP BY
    1
  HAVING
    max(cdc.finished_date) BETWEEN TIMESTAMP '{{FROM}}' AND TIMESTAMP '{{TO}}'
),
_incidents_for_deployments as (
  SELECT
    i.id as incident_id,
    i.created_date as incident_create_date,
    i.resolution_date as incident_resolution_date,
    fd.deployment_id as caused_by_deployment,
    fd.deployment_finished_date,
    strftime(fd.deployment_finished_date, '%y/%m') as deployment_finished_month
  FROM
    incidents i
    left join project_incident_deployment_relationships pim on i.id = pim.id
    join _deployments fd on pim.deployment_id = fd.deployment_id
  WHERE
    i.resolution_date BETWEEN TIMESTAMP '{{FROM}}' AND TIMESTAMP '{{TO}}'
),
_recovery_time_ranks as (
  SELECT
    *,
    percent_rank() over(
      order by
        trunc((epoch(incident_resolution_date) - epoch(deployment_finished_date)) / 60)
    ) as ranks
  FROM
    _incidents_for_deployments
),
_median_recovery_time as (
  SELECT
    max(
      CAST(trunc((epoch(incident_resolution_date) - epoch(deployment_finished_date)) / 60) AS BIGINT)
    ) as median_recovery_time
  FROM
    _recovery_time_ranks
  WHERE
    ranks <= 0.5
),

_is_collected_data as(
  SELECT
    CASE
      WHEN EXISTS(select COUNT(d.deployment_id) from _deployments) = 0 AND EXISTS(select COUNT(i.incident_id) FROM incidents) = 0 THEN 'No deployments and incidents'
      WHEN EXISTS(select COUNT(d.deployment_id) from _deployments) = 0 THEN 'No Deployments'
      WHEN EXISTS(select COUNT(i.incident_id) FROM incidents) = 0 THEN 'No Incidents'
      Else 'No incidents are mapped to deployments'
    END AS is_collected
  FROM
    _deployments d, _incidents_for_deployments i
),

_metric_recovery_time_2023_report as(
  SELECT
    CASE
      WHEN ('{{REPORT}}') = '2023' THEN CASE
        WHEN is_collected = 'No deployments and incidents' THEN 'N/A. Please check if you have collected deployments and incidents.'
        WHEN is_collected = 'No Deployments' THEN 'N/A. Please check if you have collected deployments.'
        WHEN is_collected = 'No Incidents' THEN 'N/A. Please check if you have collected incidents.'
        WHEN median_recovery_time < 60 THEN CONCAT(round(median_recovery_time / 60, 1), '(elite)')
        WHEN median_recovery_time < 24 * 60 THEN CONCAT(round(median_recovery_time / 60, 1), '(high)')
        WHEN median_recovery_time < 7 * 24 * 60 THEN CONCAT(round(median_recovery_time / 60, 1), '(medium)')
        WHEN median_recovery_time >= 7 * 24 * 60 THEN CONCAT(round(median_recovery_time / 60, 1), '(low)')
        ELSE 'No data'
      END
    END AS median_recovery_time
  FROM
    _median_recovery_time,
    _is_collected_data
),
_incidents as (
  -- get the incidents created within the selected time period in the top-right corner
  SELECT
    distinct i.id,
    cast(lead_time_minutes as BIGINT) as lead_time_minutes
  FROM
    incidents i
    join project_mapping pm on i.scope_id = pm.row_id
    and pm."table" = i."table"
  WHERE
    pm.project_name in ('{{PROJECT}}')
    and i.resolution_date BETWEEN TIMESTAMP '{{FROM}}' AND TIMESTAMP '{{TO}}'
),
_median_mttr_ranks as(
  SELECT
    *,
    percent_rank() over(
      order by
        lead_time_minutes
    ) as ranks
  FROM
    _incidents
),
_median_mttr as(
  SELECT
    max(lead_time_minutes) as median_time_to_resolve
  FROM
    _median_mttr_ranks
  WHERE
    ranks <= 0.5
),
_metric_mttr_2021_report as(
  SELECT
    CASE
      WHEN ('{{REPORT}}') = '2021' THEN CASE
        WHEN median_time_to_resolve < 60 THEN CONCAT(round(median_time_to_resolve / 60, 1), '(elite)')
        WHEN median_time_to_resolve < 24 * 60 THEN CONCAT(round(median_time_to_resolve / 60, 1), '(high)')
        WHEN median_time_to_resolve < 7 * 24 * 60 THEN CONCAT(
          round(median_time_to_resolve / 60, 1),
          '(medium)'
        )
        WHEN median_time_to_resolve >= 7 * 24 * 60 THEN CONCAT(round(median_time_to_resolve / 60, 1), '(low)')
        ELSE 'N/A. Please check if you have collected incidents.'
      END
    END AS median_time_to_resolve
  FROM
    _median_mttr
)
SELECT
  median_recovery_time AS median_time_in_hour
FROM
  _metric_recovery_time_2023_report
WHERE
  ('{{REPORT}}') = '2023'
UNION
SELECT
  median_time_to_resolve AS median_time_to_resolve
FROM
  _metric_mttr_2021_report
WHERE
  ('{{REPORT}}') = '2021';

-- panel: monthly
with _deployments as(
	SELECT
		strftime(deployment_finished_date,'%y/%m') as month,
		count(cicd_deployment_id) as deployment_count
	FROM (
		SELECT
			cdc.cicd_deployment_id,
			max(cdc.finished_date) as deployment_finished_date
		FROM cicd_deployment_commits cdc
		JOIN project_mapping pm on cdc.cicd_scope_id = pm.row_id and pm."table" = 'cicd_scopes'
		WHERE
			pm.project_name in ('{{PROJECT}}')
			and cdc.result = 'SUCCESS'
			and cdc.environment = 'PRODUCTION'
		GROUP BY 1
		HAVING max(cdc.finished_date) BETWEEN TIMESTAMP '{{FROM}}' AND TIMESTAMP '{{TO}}'
	) _production_deployments
	GROUP BY 1
)

SELECT
	cm.month,
	case when d.deployment_count is null then 0 else d.deployment_count end as "Deployment Count"
FROM
	calendar_months cm
	LEFT JOIN _deployments d on cm.month = d.month
	WHERE month_timestamp between CAST(date_trunc('month', TIMESTAMP '{{FROM}}') AS date) AND CAST(date_trunc('month', TIMESTAMP '{{TO}}') AS date)
	ORDER BY cm.month_timestamp;

-- panel: pr_cycle_time
-- From DevLake's Engineering Throughput and Cycle Time dashboard ("PR Cycle Time [Merged PRs]", monthly interval).
with _prs as(
  SELECT
    pr.id,
    pr.merged_date as pr_merged_date,
    -- convert null to 0 if a PR has no cycle_time to make sure cycle_time equals the sum of the four metrics below
		coalesce(prm.pr_cycle_time/60,0) as cycle_time
  FROM pull_requests pr
    join project_pr_metrics prm on pr.id = prm.id
    join project_mapping pm on pr.base_repo_id = pm.row_id and pm."table" = 'repos'
  WHERE
    pr.merged_date BETWEEN TIMESTAMP '{{FROM}}' AND TIMESTAMP '{{TO}}'
    and pr.created_date >= CAST(date_trunc('month', TIMESTAMP '{{FROM}}') AS date) + INTERVAL 1 MONTH
    and pm.project_name in ('{{PROJECT}}')
  GROUP BY 1,2,3
)

SELECT
  CAST(CAST(pr_merged_date AS date) - INTERVAL (day(CAST(pr_merged_date AS date)) - 1) DAY AS date) as time,
  avg(cycle_time) as "PR Cycle Time(h)"
FROM _prs
GROUP BY 1
ORDER BY 1;
