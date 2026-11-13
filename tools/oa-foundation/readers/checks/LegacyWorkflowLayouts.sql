-- B05-L01: read-only legacy workflow layout coverage check.
-- Only static definitions for workflows already present in workflow_base.
-- Nonzero results require legacy layout parsing; they do not prove runtime use.
SELECT 'workflow_nodemode' AS source,
       COUNT_BIG(*) AS config_rows,
       SUM(CAST(COALESCE(DATALENGTH(m.modedesc),0) AS bigint)) AS text_bytes
FROM dbo.workflow_nodemode m
WHERE EXISTS (
    SELECT 1 FROM dbo.workflow_base b
    JOIN dbo.workflow_flownode f ON f.workflowid=b.id
    WHERE b.id=m.workflowid AND f.nodeid=m.nodeid
      AND NOT EXISTS (
          SELECT 1 FROM dbo.workflow_nodebase n
          WHERE n.id=f.nodeid AND n.requestid IS NOT NULL AND n.requestid<>0
      )
)
UNION ALL
SELECT 'workflow_formmode',COUNT_BIG(*),
       SUM(CAST(COALESCE(DATALENGTH(m.modedesc),0) AS bigint))
FROM dbo.workflow_formmode m
WHERE EXISTS (
    SELECT 1 FROM dbo.workflow_base b
    WHERE b.formid=m.formid AND b.isbill=m.isbill
);
