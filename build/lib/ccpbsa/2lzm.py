from ccpbsa import *

x = DataGenerator(
    '2lzm.pdb',
#    'mutations_2lzm.txt',
    'mut.txt',
    'flags.txt',
    '2lzm/energy.mdp',
    dummy=True
)

y = DataCollector(x)
y.search_data()

print("G folded mean values:")
print(y.G_mean)
y.G.to_csv("G_fold.csv")
y.G_mean.to_csv("G_fold_mean.csv")

y.dstability(gxg_table)
print("dG folded values:")
print(y.dG)
print("dG unfolded values (GXG):")

print(y.dG_unfld)
y.dG.to_csv("dG_fold.csv")
y.dG_unfld.to_csv("dG_unfold.csv")

y.ddstability()
print("ddG values:")
print("without fit:")
print(y.ddG)
y.ddG.to_csv("ddG.csv")
ddG_fit = y.fitstability(**parameters)
print("with fit:")
print(ddG_fit)
y.ddG.to_csv("ddG_fit.csv")
