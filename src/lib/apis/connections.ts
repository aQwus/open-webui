import { WEBUI_API_BASE_URL } from '$lib/constants';

/**
 * Connection status response for all integrations
 */
export interface ConnectionStatus {
    connected: boolean;
    connection_id?: string;
    status?: string;
    error?: string;
}

export interface ConnectionStatusResponse {
    attio: ConnectionStatus;
    notion: ConnectionStatus;
}

export interface InitiateConnectionResponse {
    redirect_url: string;
    connection_id?: string;
    status: string;
}

/**
 * Get connection status for all integrations
 */
export const getConnectionStatus = async (token: string): Promise<ConnectionStatusResponse> => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/status`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};

/**
 * Initiate Attio OAuth connection
 */
export const initiateAttioConnection = async (
    token: string
): Promise<InitiateConnectionResponse> => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/attio/initiate`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};

/**
 * Check if Attio connection is complete (for polling)
 */
export const checkAttioConnection = async (token: string): Promise<ConnectionStatus> => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/attio/check`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};

/**
 * Get Attio sync status for current user
 */
export const getAttioSyncStatus = async (token: string) => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/attio/sync-status`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};

/**
 * Manually trigger Attio sync
 */
export const triggerAttioSync = async (token: string) => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/attio/trigger-sync`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};

/**
 * Initiate Notion OAuth connection
 */
export const initiateNotionConnection = async (token: string) => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/notion/initiate`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};

/**
 * Check if Notion connection is complete (for polling)
 */
export const checkNotionConnection = async (token: string): Promise<ConnectionStatus> => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/notion/check`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};

/**
 * Get Notion sync status for current user
 */
export const getNotionSyncStatus = async (token: string) => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/notion/sync-status`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};

/**
 * Manually trigger Notion sync
 */
export const triggerNotionSync = async (token: string) => {
    const res = await fetch(`${WEBUI_API_BASE_URL}/connections/notion/trigger-sync`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        }
    }).catch((err) => {
        console.error(err);
        return null;
    });

    if (!res || !res.ok) {
        throw await res?.json();
    }

    return res.json();
};
