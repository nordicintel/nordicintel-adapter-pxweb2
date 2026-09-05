# nordicintel-adapter-pxweb2

Harvesting adapter for the PxAPI v2 protocol.

The package implements the structural `nordicintel_core.models.NordicIntelAdapter`
protocol. Hosts inject a `ProviderDefinition`, resolved secrets, and the shared
`AsyncHttpClient`; the adapter performs no database access.

During local development, install core into this repository's virtual environment as
an editable dependency:

```powershell
uv pip install -e "C:\Users\ruben\Github\nordicintel-core[http]"
```

Then import the adapter from `nordicintel_adapter_pxweb2`.
