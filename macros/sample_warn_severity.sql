{% macro sample_warn_severity() %}
    {%- set root = var("parquet_root", "data/sample/rehearsal") | string -%}
    {%- set root = root[:-1] if root.endswith("/") else root -%}
    {{- return(
        "warn"
        if (
            target.name == "ci"
            or (
                target.name == "dev"
                and root
                in [
                    "data/sample/rehearsal",
                    invocation_args_dict.get("project_dir")
                    ~ "/data/sample/rehearsal",
                ]
            )
        )
        else "error"
    ) -}}
{% endmacro %}
