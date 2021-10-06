"""
TODO:
- washout
- add tests?
"""
from __future__ import annotations
from typing import Callable, NamedTuple, Optional, Tuple, TypeVar
import jax.numpy as jnp


# type variable for jax array type (varies)
Array = TypeVar('Array')


class ESNConfig(NamedTuple):
    """A configuration for the ESN.

    :param input_size: dimension of the input
    :param reservoir_size: number of neurons in the reservoir
    :param output_size: dimension of the output
    :param init_weights: function to initialize reservoir weights (W)
        e.g. jax.random.uniform or jax.random.normal
        (key, shape) -> array
    :param init_weights_in: function to initialize input weights (W_in)
        e.g. jax.random.uniform or jax.random.normal
        (key, shape) -> array
    :param rho: desired spectral radius of reservoir weight matrix
        if None, spectral radius is not modified
    :param feedback: whether or not to include feedback connections
        from the output to the reservoir
        defaults to False
    """
    input_size: int
    reservoir_size: int
    output_size: int
    init_weights: Callable
    init_weights_in: Callable
    init_weights_b: Callable
    rho: Optional[float] = None
    feedback: bool = False


class Optimizer:
    def __init__(self):
        pass

    def fit(self, xt, ut, yt_hat, skip_connections=False):
        pass


class LinearRegression(Optimizer):
    def __init__(self):
        """Initialize linear regression optimizer."""
        super().__init__()

    def fit(self, xt, ut, yt_hat, skip_connections=False):
        """
        Fit the linear regression.

        :param xt: collected reservoir states (T, N)
        :param ut: input (T, K)
        :param yt_hat: desired output (T, L)
        :return W: weight matrix of size (N, N)
        """
        if skip_connections:
            S = jnp.concatenate([xt, ut], axis=1)
        else:
            S = xt.copy()
        w_out = jnp.dot(jnp.linalg.pinv(S), yt_hat).T
        return w_out


class RidgeRegression(Optimizer):
    def __init__(self, alpha: float = 1e-8):
        """
        Initialize ridge regression optimizer.

        :param alpha: regularization parameter.
        """
        super().__init__()
        self.alpha = alpha

    def fit(self, xt, ut, yt_hat, skip_connections=False):
        """
        Fit the ridge regression.

        :param xt: collected reservoir states (T, N)
        :param ut: input (T, K)
        :param yt_hat: desired output (T, L)
        :return W: weight matrix of size (N, N)
        """
        if skip_connections:
            S = jnp.concatenate([xt, ut], axis=1)
        else:
            S = xt.copy()
        R = jnp.dot(S.T, S) / xt.shape[0]
        D = yt_hat
        P = jnp.dot(S.T, D) / xt.shape[0]
        w_out = jnp.dot(
            jnp.linalg.inv(R + self.alpha * jnp.eye(R.shape[0])),
            P).T
        return w_out


class ESN:
    def __init__(self, key: Array, config: ESNConfig,
                 skip_connections=False) -> None:
        """
        Set up ESN and initialize the weight matrices (and bias).

        :param key: JAX PRNG key
        :param :
        """
        (
            self.input_size,
            self.reservoir_size,
            self.output_size,
            self.init_weights,
            self.init_weights_in,
            self.init_weights_b,
            self.rho,
            self.feedback
        ) = config
        self.skip_connections = skip_connections

        # PRNG key
        self.key = key

        # shortcut
        K, N, L = self.get_sizes()

        # initialize weights
        self.w_in = self.init_weights_in(key, (N, K))
        self.w = self.init_weights(key, (N, N))
        self.b = self.init_weights_b(key, (N, 1))
        self.w_fb = self.init_weights(key, (N, L))\
            if self.feedback else jnp.zeros((N, L))
        if self.skip_connections:
            self.w_out = self.init_weights(key, (L, N + K))
        else:
            self.w_out = self.init_weights(key, (L, N))

        # normalize spectral radius (if desired)
        if self.rho is not None:
            self.normalize_spectral_radius(self.rho)

    def get_sizes(self) -> tuple[int, int, int]:
        """
        Simple helper function to get dimensions of the ESN.
        :return K, N, L: input size, reservoir size, output size
        """
        return self.input_size, self.reservoir_size, self.output_size

    def normalize_spectral_radius(self, rho: float = 1.0) -> None:
        """
        Normalize the reservoir's internal weight matrix to a desired
        spectral radius. This helps to keep the reservoir in a stable
        regime. See [TODO: reference].

        :param rho: desired spectral radius
        """
        # compute current spectral radius
        current_rho = max(abs(jnp.linalg.eig(self.w)[0]))
        # scale weight matrix to desired spectral radius
        self.w *= rho / current_rho

    def _forward(self, ut: Array, x_init: Optional[Array] = None,
                 collect_states: bool = True, C: Optional[Array] = None)\
            -> Tuple[Array, ...]:
        """
        Forward pass for training, collects all reservoir states and outputs.

        :param ut: (T, K)
        :param x_init: (N, 1)
        :return xt: (T, N)
        :return yt: (T, L)
        """
        _, N, L = self.get_sizes()
        T = ut.shape[0]
        if collect_states:
            xt = []
        yt = []
        # initial reservoir state (default: zero)
        x = jnp.zeros((N, 1)) if x_init is None else x_init.copy()
        y = jnp.zeros((L, 1))
        # time loop
        for t in range(T):
            u = ut[t:t+1, :].T
            if collect_states:
                xt.append(x)
            # state update (with or without feedback)
            x = jnp.dot(self.w_in, u) + jnp.dot(self.w, x) + self.b
            if self.feedback:
                x += jnp.dot(self.w_fb, y)
            x = jnp.tanh(x)
            # use conceptor, if given
            if C is not None:
                x = jnp.dot(C, x)
            # compute output
            if self.skip_connections:
                y = jnp.dot(self.w_out, jnp.concatenate([x, u], axis=0))
            else:
                y = jnp.dot(self.w_out, x)
            yt.append(y)
        # collect outputs and reservoir states into matrices
        yt = jnp.concatenate(yt, axis=1).T
        if collect_states:
            xt = jnp.concatenate(xt, axis=1).T
            return xt, yt
        else:
            return yt

    def harvest_states(self, ut: Array, x_init: Optional[Callable] = None,
                       C: Optional[Array] = None) -> Tuple[Array, Array]:
        """
        Forward pass for training, collects all reservoir states and outputs.

        :param ut: (T, K)
        :param x_init: (N, 1)
        :return xt: (T, N)
        :return yt: (T, L)
        """
        return self._forward(ut, x_init, collect_states=True, C=C)

    def forward(self, ut: Array, x_init: Optional[Callable] = None,
                C: Optional[Array] = None) -> Array:
        """
        Forward pass function, only collects and returns outputs.

        :param ut: (T, K)
        :param x_init: (N, 1)
        :return yt: (T, L)
        """
        return self._forward(ut, x_init, collect_states=False, C=C)

    def compute_weights(self, xt: Array, ut: Array, yt_hat: Array,
                        optimizer: Optimizer = LinearRegression()) -> Array:
        """
        Compute updated weights with the given optimizer.

        :param xt: collected reservoir states (T, N)
        :param ut: input (T, K)
        :param yt_hat: desired output (T, L)
        :param optimizer: optimizer object, e.g. linear regression.
        :return W: weight matrix of size (N, N)
        """
        return optimizer.fit(xt, ut, yt_hat,
                             skip_connections=self.skip_connections)

    def update_weights(self, xt: Array, ut: Array, yt_hat: Array,
                       optimizer: Optimizer = LinearRegression()):
        """
        Compute and update the weights with the given optimizer.

        :param xt: collected reservoir states (T, N)
        :param ut: input (T, K)
        :param yt_hat: desired output (T, L)
        :param optimizer: optimizer object, e.g. linear regression.
        """
        self.w_out = self.compute_weights(xt, ut, yt_hat, optimizer=optimizer)
