"""Linear static FEA of the Ironclad CanSat v2 rib-cage frame under landing loads.
Units: mm, N, MPa (N/mm^2), tonnes for mass (so density g/mm^3 * 1e-6 -> t/mm^3; accel mm/s^2).
Usage: python3 run_fea.py mesh.npz [label]"""
import sys, json, time
import numpy as np
from skfem import MeshTet, Basis, FacetBasis, ElementTetP1, ElementVector, asm, condense, BilinearForm, LinearForm
from skfem.models.elasticity import linear_elasticity, lame_parameters
from skfem.helpers import dot
import pyamg
from scipy.sparse.linalg import cg

meshfile = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else "run"
d = np.load(meshfile)
m = MeshTet(d["nodes"].T.astype(float), d["elems"].T.astype(np.int64))
e = ElementVector(ElementTetP1())
ib = Basis(m, e)

MAT = {"PLA": (2300.0, 0.35, 30.0), "PETG": (2000.0, 0.38, 35.0)}  # E MPa, nu, conservative printed strength MPa
G = 9810.0  # mm/s^2
RHO = 1.24e-9  # t/mm^3 (PLA)

# component masses sitting on each deck (grams, estimates from typical module weights; labelled as such)
DECKS = {"B": (61.6, 21.0), "C": (73.6, 21.0), "D": (87.6, 23.0)}
LID_G = 12.3
x, y, z = m.p
r = np.hypot(x, y)


def facets_at(zv, rmax=29.9, tol=0.06):
    mid = m.p[:, m.facets].mean(axis=1)
    sel = (np.abs(mid[2] - zv) < tol) & (np.hypot(mid[0], mid[1]) < rmax)
    sel &= np.isin(m.facets, m.boundary_facets()).all(axis=0) if False else sel
    bf = m.boundary_facets()
    return bf[sel[bf]]


results = {}
E, nu = 2300.0, 0.35
lam, mu = lame_parameters(E, nu)
t0 = time.time()
K = asm(linear_elasticity(lam, mu), ib)
print("assembled", round(time.time()-t0,1), flush=True)
fields = {}
import os as _os
CASES = {"flat": (0, "flat"), "tilted30": (30, "edge")}
for case, (tilt_deg, support) in [(k, v) for k, v in CASES.items() if k in _os.environ.get("CASES", "flat,tilted30").split(",")]:
    a = 100 * G   # solve at 100 g; linear, so scale afterwards
    th = np.radians(tilt_deg)
    dirv = np.array([np.sin(th), 0.0, -np.cos(th)])  # can tilted so its +x edge lands first

    @LinearForm
    def body(v, w):
        return RHO * a * (dirv[0] * v[0] + dirv[1] * v[1] + dirv[2] * v[2])
    f = asm(body, ib)
    for name, (zt, grams) in list(DECKS.items()) + [("lid", (112.0, LID_G))]:
        fac = facets_at(zt, rmax=40 if name == "lid" else 29.9)
        A = asm(LinearForm(lambda v, w: v), FacetBasis(m, ElementTetP1(), facets=fac)).sum()
        vec = (grams * 1e-6 * a / A) * dirv
        f += asm(LinearForm(lambda v, w, vec=vec: vec[0] * v[0] + vec[1] * v[1] + vec[2] * v[2]), FacetBasis(m, e, facets=fac))
    if support == "flat":
        fix_nodes = np.where((z < 8.05) & (r >= 24.9))[0]
    else:
        fix_nodes = np.where((z < 8.05) & (r >= 24.9) & (x > 33 * np.cos(np.radians(40))))[0]
    D = ib.nodal_dofs[:, fix_nodes].ravel()
    Kc, fc, uc, I = condense(K, f, D=D)
    t1 = time.time()
    # rigid-body near-nullspace for elasticity AMG
    npn = m.p.shape[1]
    Bfull = np.zeros((3 * npn, 6))
    nd = ib.nodal_dofs
    px, py, pz = m.p
    for k in range(3):
        Bfull[nd[k], k] = 1.0
    Bfull[nd[0], 3] = -py; Bfull[nd[1], 3] = px
    Bfull[nd[1], 4] = -pz; Bfull[nd[2], 4] = py
    Bfull[nd[0], 5] = pz;  Bfull[nd[2], 5] = -px
    Bc = Bfull[I]
    import os
    if os.environ.get("SOLVER") == "pardiso":
        import pypardiso
        sol = pypardiso.spsolve(Kc.tocsr(), fc)
    else:
        ml = pyamg.smoothed_aggregation_solver(Kc, B=Bc, symmetry="symmetric", max_coarse=1000)
        res = []
        sol = ml.solve(fc, tol=1e-9, accel="cg", maxiter=3000, residuals=res)
        print("iters", len(res), flush=True)
    print(case, "solved", round(time.time()-t1,1), "resid", float(np.linalg.norm(fc-Kc@sol)/np.linalg.norm(fc)), flush=True)
    u = np.zeros(K.shape[0]); u[I] = sol
    U = u[ib.nodal_dofs]
    tets = m.t
    P = m.p[:, tets]
    Ue = U[:, tets]
    J = np.transpose(P[:, 1:, :] - P[:, [0], :], (2, 0, 1))
    Jinv = np.linalg.inv(J)
    dU = np.transpose(Ue[:, 1:, :] - Ue[:, [0], :], (2, 0, 1))
    grad = np.einsum('nij,njk->nik', dU, Jinv)
    eps = 0.5 * (grad + np.transpose(grad, (0, 2, 1)))
    tr = np.trace(eps, axis1=1, axis2=2)
    s_ = 2 * mu * eps + lam * tr[:, None, None] * np.eye(3)
    vm = np.sqrt(0.5 * ((s_[:, 0, 0] - s_[:, 1, 1]) ** 2 + (s_[:, 1, 1] - s_[:, 2, 2]) ** 2 + (s_[:, 2, 2] - s_[:, 0, 0]) ** 2)
                 + 3 * (s_[:, 0, 1] ** 2 + s_[:, 1, 2] ** 2 + s_[:, 0, 2] ** 2))
    cen = P.mean(axis=1)
    fields[case] = (vm, cen, U)
    np.savez(f"field_{label}_{case}.npz", vm=vm, cen=cen, U=U)
    for g_load in (144, 538):
        k = g_load / 100.0
        p999 = float(np.percentile(vm, 99.9)) * k
        vmax = float(vm.max()) * k
        imax = int(np.argmax(vm))
        for matname, (Em, num, strength) in MAT.items():
            results[f"{case}_{g_load}g|{matname}"] = {
                "g_load": g_load, "tilt_deg": tilt_deg, "material": matname,
                "max_vm_MPa": round(vmax, 1), "p99_9_vm_MPa": round(p999, 1),
                "max_disp_mm": round(float(np.abs(U).max()) * k * 2300.0 / Em, 3), "strength_MPa": strength,
                "SF_on_p99_9": round(strength / p999, 2), "SF_on_max": round(strength / vmax, 2),
                "hotspot_xyz": [round(float(c), 1) for c in cen[:, imax]]}
            print(case, g_load, matname, results[f"{case}_{g_load}g|{matname}"], flush=True)
json.dump(results, open(f"results_{label}_{_os.environ.get('CASES','all')}.json", "w"), indent=1)
print("nodes", m.p.shape[1], "tets", m.t.shape[1])
