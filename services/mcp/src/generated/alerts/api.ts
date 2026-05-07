/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const HogFunctionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFunctionsListQueryParams = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}).optional(),
    created_by: zod.number().optional(),
    enabled: zod.boolean().optional(),
    id: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    type: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
    updated_at: zod.iso.datetime({}).optional(),
})

export const HogFunctionsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFunctionsCreateBodyNameMaxOne = 400

export const hogFunctionsCreateBodyInputsSchemaItemRequiredDefaultOne = false
export const hogFunctionsCreateBodyInputsSchemaItemSecretDefaultOne = false
export const hogFunctionsCreateBodyInputsSchemaItemHiddenDefaultOne = false
export const hogFunctionsCreateBodyFiltersOneSourceDefaultOne = `events`
export const hogFunctionsCreateBodyMaskingOneTtlMinOne = 60
export const hogFunctionsCreateBodyMaskingOneTtlMaxOne = 86400

export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemRequiredDefaultOne = false
export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemSecretDefaultOne = false
export const hogFunctionsCreateBodyMappingsItemInputsSchemaItemHiddenDefaultOne = false
export const hogFunctionsCreateBodyMappingsItemFiltersSourceDefaultOne = `events`
export const hogFunctionsCreateBodyTemplateIdMaxOne = 400

export const hogFunctionsCreateBodyExecutionOrderMinOne = 0
export const hogFunctionsCreateBodyExecutionOrderMaxOne = 32767

export const HogFunctionsCreateBody = /* @__PURE__ */ zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod.string().max(hogFunctionsCreateBodyNameMaxOne).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                        'posthog_business_hours',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags\n* `posthog_business_hours` - posthog_business_hours'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemRequiredDefaultOne),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemSecretDefaultOne),
                hidden: zod.boolean().default(hogFunctionsCreateBodyInputsSchemaItemHiddenDefaultOne),
                description: zod.string().optional(),
                templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsCreateBodyFiltersOneSourceDefaultOne),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsCreateBodyMaskingOneTtlMinOne)
                .max(hogFunctionsCreateBodyMaskingOneTtlMaxOne)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                    'posthog_business_hours',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags\n* `posthog_business_hours` - posthog_business_hours'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemRequiredDefaultOne),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemSecretDefaultOne),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsCreateBodyMappingsItemInputsSchemaItemHiddenDefaultOne),
                            description: zod.string().optional(),
                            templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsCreateBodyMappingsItemFiltersSourceDefaultOne),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsCreateBodyTemplateIdMaxOne)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsCreateBodyExecutionOrderMinOne)
        .max(hogFunctionsCreateBodyExecutionOrderMaxOne)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

export const HogFunctionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFunctionsPartialUpdateBodyNameMaxOne = 400

export const hogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefaultOne = false
export const hogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefaultOne = false
export const hogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefaultOne = false
export const hogFunctionsPartialUpdateBodyFiltersOneSourceDefaultOne = `events`
export const hogFunctionsPartialUpdateBodyMaskingOneTtlMinOne = 60
export const hogFunctionsPartialUpdateBodyMaskingOneTtlMaxOne = 86400

export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemRequiredDefaultOne = false
export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemSecretDefaultOne = false
export const hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemHiddenDefaultOne = false
export const hogFunctionsPartialUpdateBodyMappingsItemFiltersSourceDefaultOne = `events`
export const hogFunctionsPartialUpdateBodyTemplateIdMaxOne = 400

export const hogFunctionsPartialUpdateBodyExecutionOrderMinOne = 0
export const hogFunctionsPartialUpdateBodyExecutionOrderMaxOne = 32767

export const HogFunctionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    type: zod
        .union([
            zod
                .enum([
                    'destination',
                    'site_destination',
                    'internal_destination',
                    'source_webhook',
                    'warehouse_source_webhook',
                    'site_app',
                    'transformation',
                ])
                .describe(
                    '* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.\n\n* `destination` - Destination\n* `site_destination` - Site Destination\n* `internal_destination` - Internal Destination\n* `source_webhook` - Source Webhook\n* `warehouse_source_webhook` - Warehouse Source Webhook\n* `site_app` - Site App\n* `transformation` - Transformation'
        ),
    name: zod
        .string()
        .max(hogFunctionsPartialUpdateBodyNameMaxOne)
        .nullish()
        .describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    inputs_schema: zod
        .array(
            zod.object({
                type: zod
                    .enum([
                        'string',
                        'number',
                        'boolean',
                        'dictionary',
                        'choice',
                        'json',
                        'integration',
                        'integration_field',
                        'email',
                        'native_email',
                        'posthog_assignee',
                        'posthog_ticket_tags',
                        'posthog_business_hours',
                    ])
                    .describe(
                        '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags\n* `posthog_business_hours` - posthog_business_hours'
                    ),
                key: zod.string(),
                label: zod.string().optional(),
                choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                required: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemRequiredDefaultOne),
                default: zod.unknown().optional(),
                secret: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemSecretDefaultOne),
                hidden: zod.boolean().default(hogFunctionsPartialUpdateBodyInputsSchemaItemHiddenDefaultOne),
                description: zod.string().optional(),
                templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
            })
        )
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(
            zod.string(),
            zod.object({
                value: zod.unknown().optional(),
                templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                bytecode: zod.array(zod.unknown()).optional(),
                order: zod.number().optional(),
                transpiled: zod.unknown().optional(),
            })
        )
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: zod
        .object({
            source: zod
                .enum(['events', 'person-updates', 'data-warehouse-table'])
                .describe(
                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                )
                .default(hogFunctionsPartialUpdateBodyFiltersOneSourceDefaultOne),
            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
            bytecode: zod.unknown().nullish(),
            transpiled: zod.unknown().optional(),
            filter_test_accounts: zod.boolean().optional(),
            bytecode_error: zod.string().optional(),
        })
        .optional()
        .describe('Event filters that control which events trigger this function.'),
    masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFunctionsPartialUpdateBodyMaskingOneTtlMinOne)
                .max(hogFunctionsPartialUpdateBodyMaskingOneTtlMaxOne)
                .describe('Time-to-live in seconds for the masking cache (60–86400).'),
            threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
            hash: zod.string().describe('Hog expression used to compute the masking hash.'),
            bytecode: zod.unknown().nullish().describe('Compiled bytecode for the hash expression. Auto-generated.'),
        })
        .nullish()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(
            zod.object({
                name: zod.string().optional(),
                inputs_schema: zod
                    .array(
                        zod.object({
                            type: zod
                                .enum([
                                    'string',
                                    'number',
                                    'boolean',
                                    'dictionary',
                                    'choice',
                                    'json',
                                    'integration',
                                    'integration_field',
                                    'email',
                                    'native_email',
                                    'posthog_assignee',
                                    'posthog_ticket_tags',
                                    'posthog_business_hours',
                                ])
                                .describe(
                                    '* `string` - string\n* `number` - number\n* `boolean` - boolean\n* `dictionary` - dictionary\n* `choice` - choice\n* `json` - json\n* `integration` - integration\n* `integration_field` - integration_field\n* `email` - email\n* `native_email` - native_email\n* `posthog_assignee` - posthog_assignee\n* `posthog_ticket_tags` - posthog_ticket_tags\n* `posthog_business_hours` - posthog_business_hours'
                                ),
                            key: zod.string(),
                            label: zod.string().optional(),
                            choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            required: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemRequiredDefaultOne),
                            default: zod.unknown().optional(),
                            secret: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemSecretDefaultOne),
                            hidden: zod
                                .boolean()
                                .default(hogFunctionsPartialUpdateBodyMappingsItemInputsSchemaItemHiddenDefaultOne),
                            description: zod.string().optional(),
                            templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
                        })
                    )
                    .optional(),
                inputs: zod
                    .record(
                        zod.string(),
                        zod.object({
                            value: zod.unknown().optional(),
                            templating: zod
                                .enum(['hog', 'liquid'])
                                .optional()
                                .describe('* `hog` - hog\n* `liquid` - liquid'),
                            bytecode: zod.array(zod.unknown()).optional(),
                            order: zod.number().optional(),
                            transpiled: zod.unknown().optional(),
                        })
                    )
                    .optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFunctionsPartialUpdateBodyMappingsItemFiltersSourceDefaultOne),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        filter_test_accounts: zod.boolean().optional(),
                    })
                    .optional(),
            })
        )
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template_id: zod
        .string()
        .max(hogFunctionsPartialUpdateBodyTemplateIdMaxOne)
        .nullish()
        .describe('ID of the template to create this function from.'),
    execution_order: zod
        .number()
        .min(hogFunctionsPartialUpdateBodyExecutionOrderMinOne)
        .max(hogFunctionsPartialUpdateBodyExecutionOrderMaxOne)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const HogFunctionsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog function.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
