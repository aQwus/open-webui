import { WEBUI_API_BASE_URL } from '$lib/constants';

export const uploadDocument = async (token: string, file: File) => {
    const data = new FormData();
    data.append('file', file);

    let error = null;

    const res = await fetch(`${WEBUI_API_BASE_URL}/documents/upload`, {
        method: 'POST',
        headers: {
            Accept: 'application/json',
            authorization: `Bearer ${token}`
        },
        body: data
    })
        .then(async (res) => {
            if (!res.ok) throw await res.json();
            return res.json();
        })
        .catch((err) => {
            error = err.detail || err.message;
            console.error(err);
            return null;
        });

    if (error) {
        throw error;
    }

    return res;
};

export const getDocuments = async (token: string = '') => {
    let error = null;

    const res = await fetch(`${WEBUI_API_BASE_URL}/documents/`, {
        method: 'GET',
        headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            authorization: `Bearer ${token}`
        }
    })
        .then(async (res) => {
            if (!res.ok) throw await res.json();
            return res.json();
        })
        .then((json) => {
            return json;
        })
        .catch((err) => {
            error = err.detail;
            console.error(err);
            return null;
        });

    if (error) {
        throw error;
    }

    return res;
};

export const deleteDocumentById = async (token: string, id: string) => {
    let error = null;

    const res = await fetch(`${WEBUI_API_BASE_URL}/documents/${id}`, {
        method: 'DELETE',
        headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            authorization: `Bearer ${token}`
        }
    })
        .then(async (res) => {
            if (!res.ok) throw await res.json();
            return res.json();
        })
        .then((json) => {
            return json;
        })
        .catch((err) => {
            error = err.detail;
            console.error(err);
            return null;
        });

    if (error) {
        throw error;
    }

    return res;
};
