"""Keep deployment secrets out of shell arguments and source control."""
import json, os
from pathlib import Path
p=Path(os.environ['AGENT_TEMPDIRECTORY'])/'soloai-parameters.json'
values={'image':f"{os.environ['ACR_NAME']}.azurecr.io/soloai:{os.environ['BUILD_BUILDID']}", 'registryName':os.environ['ACR_NAME'],'modelResourceName':os.environ['MODEL_RESOURCE'],'modelDeployment':os.environ['MODEL_DEPLOYMENT'],'databasePassword':os.environ['DATABASE_PASSWORD'],'publicOrigin':os.environ['PUBLIC_ORIGIN']}
p.write_text(json.dumps({'$schema':'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#','contentVersion':'1.0.0.0','parameters':{k:{'value':v} for k,v in values.items()}}))
p.chmod(0o600)
