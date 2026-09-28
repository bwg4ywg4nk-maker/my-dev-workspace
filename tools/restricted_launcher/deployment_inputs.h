/* Deployment-owner input, compiled into the signed launcher. Replace these
 * absent bindings only with independently reviewed/authenticated package pins,
 * exact v2 identity documents/artifacts and matching startup/attachment inputs.
 * No runtime file, argv, environment, Python object, or auto-collected digest
 * may populate this trust anchor. Empty defaults deliberately deny loading. */
static const struct pa_startup_binding pa_deployment_startup = {0};
static const struct pa_attachment_binding pa_deployment_attachment = {0};
